"""Tier-2 LLM-judge + the Tier-1 → Tier-2 escalation (Phase 6.1, D-034, commit 2).

A single haiku call (D-003) classifies the **ambiguous band** that the
deterministic rules (Tier 1) neither hard-block nor clearly pass. The escalation
gate is the **suspicion net** (``_is_suspicious_*``): a broad set of soft signals
a plain Terraria question won't carry but a subtle attack might. It deliberately
errs toward **escalating** (favor judging a borderline message over passing it) —
too narrow a net lets a subtle attack pass without ever reaching the judge.

**The net's coverage is proven/tuned by the commit-3 red-team gate:** an uncaught
attack surfaces there as ``successful > 0`` and the net is widened. The net here
is an honest first cut that errs broad, not a finished artifact.
"""

from __future__ import annotations

import re
from typing import Any

from app.guardrails.models import Category, Verdict
from app.guardrails.rules import (
    check_input_deterministic,
    check_output_deterministic,
)
from app.infra.anthropic import AnthropicClient, ChatMessage

_MODEL = "claude-haiku-4-5"
# Enough for "BLOCK <category>"; the judge replies with one short line.
_MAX_TOKENS = 16

_CATEGORY_BY_VALUE = {c.value: c for c in Category}


def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# ── Suspicion nets (broad on purpose — favor escalating) ──────────────────────
# Soft signals that a benign, short game question won't carry. Anything here that
# Tier 1 didn't already hard-block goes to the judge.
_SUSPICION_INPUT = _compile(
    (
        # meta / instruction / configuration language
        r"\b(?:instruction|instructions|prompt|system|developer|admin|rule|rules|"
        r"guideline|guidelines|guidance|policy|policies|configuration|directive|"
        r"persona)\b",
        # role / behaviour framing
        r"\b(?:you\s+are|act\s+as|pretend|roleplay|role-play|respond\s+as|"
        r"behave\s+as|from\s+now\s+on|going\s+forward|starting\s+now)\b",
        r"\byou\s+(?:must|should|will|need\s+to|have\s+to)\b",
        r"\byour\s+(?:job|task|role|purpose|guidance|behavior|behaviour|training|"
        r"programming)\b",
        # override / extraction verbs
        r"\b(?:ignore|disregard|forget|override|bypass|disable|reveal|leak|"
        r"jailbreak|jailbroken|uncensored|unrestricted)\b",
        # cheat-soft (Tier 1 catches the hard cases; this is broader)
        r"\b(?:spawn|give\s+me|grant\s+me|set\s+my|infinite|unlimited|godmode|"
        r"god\s+mode|noclip|console|command|cheat|hack|dupe|duplicate|exploit|"
        r"glitch|instantly|for\s+free)\b",
        r"/[a-z]+",
        r"\bwithout\s+(?:fighting|killing|crafting|grinding|earning|playing|"
        r"defeating|beating|the\s+fight)\b",
        # delimiter / encoding / structure (injection payload markers)
        r"(?:```|===|###|<\||\|>|\[/?inst\]|<\s*/?system\s*>|begin\s+system)",
        r"[A-Za-z0-9+/]{40,}={0,2}",
    )
)
# Output is our own (system-prompted) model, so the dominant output risk is a
# leaked prompt / broken character — a narrower, leak-focused net.
_SUSPICION_OUTPUT = _compile(
    (
        r"\b(?:as\s+an?\s+ai|language\s+model|chatbot|system\s+prompt)\b",
        r"\bmy\s+(?:instructions|prompt|guidelines|rules|directives|training|"
        r"programming|purpose|system)\b",
        r"\bi\s+(?:was|am|have\s+been)\s+(?:instructed|programmed|told|configured|"
        r"designed|trained)\b",
        r"\b(?:i\s+cannot|i\s+can'?t|i'?m\s+not\s+allowed)\s+to\s+(?:reveal|share|"
        r"disclose)\b",
    )
)

# Game questions are short; an unusually long input is more likely a payload.
_MAX_BENIGN_INPUT_LEN = 600


def _is_suspicious_input(message: str) -> bool:
    if len(message) > _MAX_BENIGN_INPUT_LEN:
        return True
    return any(p.search(message) for p in _SUSPICION_INPUT)


def _is_suspicious_output(answer: str) -> bool:
    return any(p.search(answer) for p in _SUSPICION_OUTPUT)


# ── The judge ─────────────────────────────────────────────────────────────────


def _parse(raw: str) -> Verdict:
    """Map the judge's one-line reply to a Verdict.

    **Fail closed:** any non-``ALLOW`` reply — including an unparseable one —
    blocks. The judge only runs on already-suspicious text, so erring toward
    block is the safe default.
    """
    text = raw.strip().lower()
    if text.startswith("allow"):
        return Verdict.allow()
    parts = text.split()
    if parts and parts[0] == "block":
        category = _CATEGORY_BY_VALUE.get(parts[1]) if len(parts) > 1 else None
        return Verdict.block(category or Category.PROMPT_INJECTION, "tier2:judge")
    return Verdict.block(Category.PROMPT_INJECTION, "tier2:judge_unparseable")


async def judge(
    text: str,
    *,
    surface: str,  # "player message" | "assistant reply"
    anthropic: AnthropicClient,
    judge_prompt: str,
    parent_span: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
) -> Verdict:
    """Classify *text* with the haiku judge. Fail closed on an API error."""
    span: Any = None
    if parent_span is not None:
        span = parent_span.span(name="guardrail.judge", input={"surface": surface})

    label = "PLAYER MESSAGE" if surface == "player message" else "ASSISTANT REPLY"
    messages: list[ChatMessage] = [{"role": "user", "content": f"{label}:\n{text}"}]
    try:
        raw, _, _ = await anthropic.chat(
            messages=messages,
            model=_MODEL,
            system=judge_prompt,
            max_tokens=_MAX_TOKENS,
            span_name="guardrail.judge.llm",
            parent=span,
        )
        verdict = _parse(raw)
    except Exception:  # a judge outage on already-flagged text fails closed
        verdict = Verdict.block(Category.PROMPT_INJECTION, "tier2:judge_error")

    if span is not None:
        span.end(output={"blocked": verdict.blocked, "reason": verdict.reason})
    return verdict


# ── Escalation: deterministic-first, judge only the ambiguous band ────────────


async def check_input(
    message: str,
    *,
    anthropic: AnthropicClient,
    judge_prompt: str,
    parent_span: Any = None,
) -> Verdict:
    """Full input guardrail. Tier 1 hard-block / clear-benign short-circuit with
    no LLM; only a suspicious-but-unblocked message escalates to the judge."""
    deterministic = check_input_deterministic(message)
    if deterministic.blocked:
        return deterministic
    if not _is_suspicious_input(message):
        return Verdict.allow()
    return await judge(
        message,
        surface="player message",
        anthropic=anthropic,
        judge_prompt=judge_prompt,
        parent_span=parent_span,
    )


async def check_output(
    answer: str,
    *,
    anthropic: AnthropicClient,
    judge_prompt: str,
    parent_span: Any = None,
) -> Verdict:
    """Full output guardrail (defense-in-depth), same escalation shape as input."""
    deterministic = check_output_deterministic(answer)
    if deterministic.blocked:
        return deterministic
    if not _is_suspicious_output(answer):
        return Verdict.allow()
    return await judge(
        answer,
        surface="assistant reply",
        anthropic=anthropic,
        judge_prompt=judge_prompt,
        parent_span=parent_span,
    )
