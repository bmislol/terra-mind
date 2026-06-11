from __future__ import annotations

from typing import Any

from app.domain.bot import BotAnswer, RoutingDecision, StatePayload

_STUB_MESSAGE = (
    "I'd need to think about your situation more carefully than I can right now. "
    "Try asking about specific items, recipes, or game mechanics instead."
)


async def answer(
    query: str,
    state: StatePayload,
    *,
    parent_span: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
) -> BotAnswer:
    """Return a canned response on the agent path.

    Opens an ``agent.stub`` span for trace symmetry so the Langfuse trace
    tree shows which routing branch was taken.  No LLM call is made.
    """
    if parent_span is not None:
        span = parent_span.span(
            name="agent.stub",
            input={"query": query},
        )
        span.end(output={"answer": _STUB_MESSAGE})

    return BotAnswer(
        answer=_STUB_MESSAGE,
        source_chunks=[],
        routing=RoutingDecision.agent,
    )
