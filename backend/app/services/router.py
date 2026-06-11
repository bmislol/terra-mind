from __future__ import annotations

from typing import Any

from app.domain.bot import RoutingDecision
from app.infra.anthropic import AnthropicClient, ChatMessage

_MODEL = "claude-haiku-4-5"
# 16 tokens is enough for "faq" or "agent" with whitespace/punctuation slack.
_MAX_TOKENS = 16


def _parse(raw: str) -> RoutingDecision:
    """Normalise the LLM's one-word reply to a RoutingDecision.

    Strips whitespace, lowercases, and matches "faq" exactly.
    Anything else — including empty strings, unknown words, or
    multi-word replies — falls back to "agent" so we never silently
    skip the more capable path.
    """
    if raw.strip().lower() == "faq":
        return RoutingDecision.faq
    return RoutingDecision.agent


async def classify(
    query: str,
    *,
    anthropic: AnthropicClient,
    router_prompt: str,
    parent_span: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
) -> RoutingDecision:
    """Classify *query* as 'faq' or 'agent' using a single Haiku call.

    Opens a ``router.classify`` span as a child of *parent_span* (when
    provided) and attaches the LLM generation to that span.
    """
    span: Any = None
    if parent_span is not None:
        span = parent_span.span(
            name="router.classify",
            input={"query": query},
        )

    messages: list[ChatMessage] = [{"role": "user", "content": query}]
    raw, _, _ = await anthropic.chat(
        messages=messages,
        model=_MODEL,
        system=router_prompt,
        max_tokens=_MAX_TOKENS,
        span_name="router.llm",
        parent=span,
    )

    decision = _parse(raw)

    if span is not None:
        span.end(output={"decision": decision.value})

    return decision
