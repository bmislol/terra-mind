"""Unit tests for app/services/agent.py.

build_agent_graph is patched at the import boundary so no LLM calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock

from app.core.prompts import LoadedPrompts
from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.pipeline import RetrievalPipeline
from app.services.agent import _FALLBACK_MESSAGE, answer

# ── Fixtures ──────────────────────────────────────────────────────────────────

_PROMPTS = LoadedPrompts(
    router="r",
    faq_answer="f",
    agent_system="a" * 100,
    class_fallback="c" * 100,
)

_CHUNK = ChunkRef(
    page_title="Megashark",
    section="stats",
    source_url="https://terraria.wiki.gg/wiki/Megashark",
    score=0.9,
)


def _mock_infra() -> tuple[AnthropicClient, RetrievalPipeline]:
    return MagicMock(spec=AnthropicClient), MagicMock(spec=RetrievalPipeline)


def _final_state(answer_text: str = "The answer is 42.") -> dict:  # type: ignore[type-arg]
    return {
        "messages": [
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "content": [TextBlock(text=answer_text, type="text")],
            },
        ],
        "chunks_seen": [_CHUNK],
        "iteration_count": 1,
        "state_payload": StatePayload(),
    }


def _make_mock_graph(ainvoke_result: dict | Exception) -> MagicMock:  # type: ignore[type-arg]
    mock_graph = MagicMock()
    if isinstance(ainvoke_result, Exception):
        mock_graph.ainvoke = AsyncMock(side_effect=ainvoke_result)
    else:
        mock_graph.ainvoke = AsyncMock(return_value=ainvoke_result)
    return mock_graph


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_agent_calls_graph_and_returns_bot_answer() -> None:
    """Happy path: graph returns a final state with TextBlock answer."""
    anthropic, retrieval = _mock_infra()
    mock_graph = _make_mock_graph(_final_state("The Megashark deals 25 base damage."))

    with patch("app.services.agent.build_agent_graph", return_value=mock_graph):
        result = await answer(
            "What damage does Megashark deal?",
            StatePayload(),
            anthropic=anthropic,
            retrieval=retrieval,
            prompts=_PROMPTS,
        )

    assert isinstance(result, BotAnswer)
    assert result.answer == "The Megashark deals 25 base damage."
    assert result.routing == RoutingDecision.agent
    assert len(result.source_chunks) == 1
    assert result.source_chunks[0].page_title == "Megashark"


async def test_agent_graph_exception_returns_fallback_bot_answer() -> None:
    """graph.ainvoke raises → service logs and returns safe fallback."""
    anthropic, retrieval = _mock_infra()
    mock_graph = _make_mock_graph(RuntimeError("graph exploded"))

    with patch("app.services.agent.build_agent_graph", return_value=mock_graph):
        result = await answer(
            "Bad query",
            StatePayload(),
            anthropic=anthropic,
            retrieval=retrieval,
            prompts=_PROMPTS,
        )

    assert result.routing == RoutingDecision.agent
    assert result.answer == _FALLBACK_MESSAGE
    assert result.source_chunks == []


async def test_agent_threads_parent_span() -> None:
    """parent_span.span() called with name='agent.run'; span.end() called."""
    anthropic, retrieval = _mock_infra()
    mock_graph = _make_mock_graph(_final_state())
    parent_span = MagicMock()
    child_span = MagicMock()
    parent_span.span.return_value = child_span

    with patch("app.services.agent.build_agent_graph", return_value=mock_graph):
        await answer(
            "question",
            StatePayload(),
            anthropic=anthropic,
            retrieval=retrieval,
            prompts=_PROMPTS,
            parent_span=parent_span,
        )

    parent_span.span.assert_called_once_with(
        name="agent.run", input={"query": "question"}
    )
    child_span.end.assert_called_once()
