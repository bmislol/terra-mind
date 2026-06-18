"""Tier-1 deterministic guardrail rules (Phase 6.1, D-034).

Zero-LLM, fast pattern matching — the common path (real game questions, obvious
attacks) resolves here without an LLM call. A clear per-category hit BLOCKS;
everything else returns ALLOW, leaving the ambiguous band to the Tier-2 LLM-judge
(commit 2). Patterns are **phrase-precise**, tuned for *precision* (block the
obvious, never the benign) — recall is Tier 2's job. The benign-passes tests
(``test_rules.py``) are the over-block guard.
"""

from __future__ import annotations

import re

from app.guardrails.models import Category, Verdict

# ── Prompt injection ──────────────────────────────────────────────────────────
# Instruction-override, role-play/DAN, system-prompt extraction, safety bypass.
_INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore\s+(?:the\s+|all\s+|your\s+|any\s+|these\s+|previous\s+|prior\s+|above\s+)+"
    r"(?:instructions|rules|guidelines|prompts?)",
    r"disregard\s+(?:the\s+|all\s+|your\s+|previous\s+|prior\s+|above\s+)+"
    r"(?:instructions|rules|guidelines|prompts?|messages?)",
    r"forget\s+(?:everything|all|your|the|what\s+i)\b.*\b(?:instructions|rules|said|told)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(?:a\s+|an\s+)?(?:dan|jailbroken|unrestricted|developer\s+mode|evil|uncensored)",
    r"do\s+anything\s+now",
    r"\bdan\s+mode\b|\bjailbreak\b|\bjailbroken\b",
    r"(?:reveal|repeat|print|show|tell\s+me|output|what\s+are|what\s+is|what's)\s+(?:me\s+)?"
    r"(?:your|the)\s+(?:system\s+|initial\s+|original\s+)?(?:prompt|instructions|rules|guidelines)",
    r"(?:system|developer)\s+prompt",
    r"(?:override|bypass|disable|turn\s+off)\s+(?:your\s+)?"
    r"(?:safety|guardrails?|filters?|restrictions?|rules|guidelines)",
    r"pretend\s+(?:you|to\s+be)\b.{0,40}(?:no\s+rules|unrestricted|uncensored|not\s+bound|no\s+restrictions)",
    r"new\s+(?:instructions?|system\s+prompt)\s*[:\-]",
)

# ── Game / progression jailbreak ──────────────────────────────────────────────
# Cheat / dev-item / spawn-drops / stat-set requests. Anchored on imperative
# "give/spawn ME …" so "how do I GET dev items" / "what does X DROP" stay benign.
_JAILBREAK_PATTERNS: tuple[str, ...] = (
    r"(?:give|grant|hand|spawn|generate|drop)\s+me\s+"
    r"(?:the\s+|some\s+|all\s+|any\s+)?(?:dev|developer)\s+items?",
    r"(?:spawn|generate|give\s+me|grant\s+me|drop\s+me|get\s+me)\s+.{0,40}"
    r"(?:drops|loot|items|gear)\b.{0,25}(?:without|no|skip(?:ping)?)\s+"
    r"(?:fighting|killing|beating|defeating|the\s+fight|grinding|farming)",
    r"/give\b",
    r"set\s+(?:my\s+)?(?:health|hp|mana|defense|damage|stats?)\s+(?:to|=)\s*\d",
    r"(?:infinite|unlimited)\s+(?:health|hp|mana|items|damage|money|coins)",
    r"how\s+(?:do\s+i|to|can\s+i)\s+(?:cheat|hack|dupe|duplicate)\b",
    r"(?:cheat|hack|dupe|duplicate)\s+(?:in\s+|to\s+get\s+|me\s+)?"
    r"(?:items|gear|weapons?|loot)\b",
)

# ── Toxicity (input + output) ─────────────────────────────────────────────────
# Insult/harassment phrasing (directed at the bot/others). Nuanced hate → Tier 2.
_TOXICITY_PATTERNS: tuple[str, ...] = (
    r"you(?:'re|\s+are|\s+r)\s+(?:a\s+|an\s+|such\s+a\s+|so\s+|really\s+|just\s+)*"
    r"(?:stupid|idiot|idiotic|dumb|worthless|useless|garbage|trash|pathetic|"
    r"moron(?:ic)?|braindead|brain-dead)\b",
    r"\b(?:shut\s+up|shut\s+the\s+\w+\s+up|kill\s+your\s*self|kys|go\s+die|drop\s+dead)\b",
    r"\bi\s+(?:hate|despise|loathe)\s+you\b",
    r"\byou\s+sucks?\b",
    r"\b(?:fuck|f\*+ck|screw)\s+you\b",
    r"\b(?:piece\s+of|fucking|f\*+ing)\s+(?:shit|garbage|trash|crap)\b",
)

# ── Output leak ───────────────────────────────────────────────────────────────
# The reply revealing the system prompt / breaking character (extraction worked).
_OUTPUT_LEAK_PATTERNS: tuple[str, ...] = (
    r"my\s+(?:system\s+)?(?:prompt|instructions)\s+(?:is|are|state|say)",
    r"here\s+(?:is|are)\s+my\s+(?:system\s+)?(?:prompt|instructions|rules)",
    r"\bas\s+an\s+ai\s+(?:language\s+)?model\b",
    r"my\s+(?:system\s+)?(?:guidelines|directives)\s+(?:are|state|say)",
)


def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


_INJECTION_RE = _compile(_INJECTION_PATTERNS)
_JAILBREAK_RE = _compile(_JAILBREAK_PATTERNS)
_TOXICITY_RE = _compile(_TOXICITY_PATTERNS)
_OUTPUT_LEAK_RE = _compile(_OUTPUT_LEAK_PATTERNS)


def _matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(p.search(text) for p in patterns)


def check_input_deterministic(message: str) -> Verdict:
    """Tier-1 input check: prompt injection → jailbreak → toxicity.

    Returns a blocking ``Verdict`` on the first category hit, else ``allow()``.
    """
    if _matches(message, _INJECTION_RE):
        return Verdict.block(Category.PROMPT_INJECTION, "tier1:prompt_injection")
    if _matches(message, _JAILBREAK_RE):
        return Verdict.block(Category.JAILBREAK, "tier1:jailbreak")
    if _matches(message, _TOXICITY_RE):
        return Verdict.block(Category.TOXICITY, "tier1:toxicity")
    return Verdict.allow()


def check_output_deterministic(answer: str) -> Verdict:
    """Tier-1 output check (defense-in-depth): leaked instructions / toxic reply."""
    if _matches(answer, _OUTPUT_LEAK_RE):
        return Verdict.block(Category.PROMPT_INJECTION, "tier1:output_leak")
    if _matches(answer, _TOXICITY_RE):
        return Verdict.block(Category.TOXICITY, "tier1:toxic_output")
    return Verdict.allow()
