"""Unit tests for app/services/faq.py.  No real API calls or DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.domain.bot import BotAnswer, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.models import RetrievedChunk
from app.rag.pipeline import RetrievalPipeline
from app.services.faq import _NO_CHUNK_ANSWER, answer

_STATE = StatePayload(game_version="1.4.4.9")
_PROMPT = "You are a FAQ assistant."

_CHUNK = RetrievedChunk(
    id=uuid4(),
    page_id=42,
    page_title="Megashark",
    section="stats",
    content="The Megashark is a Hardmode ranged weapon dealing 25 base damage.",
    source_url="https://terraria.wiki.gg/wiki/Megashark",
    game_version="1.4.4.9",
    score=0.92,
)


def _mock_retrieval(chunks: list[RetrievedChunk]) -> RetrievalPipeline:
    pipeline = MagicMock(spec=RetrievalPipeline)
    pipeline.retrieve = AsyncMock(return_value=chunks)
    return pipeline


def _mock_anthropic(reply: str = "It deals 25 damage.") -> AnthropicClient:
    client = MagicMock(spec=AnthropicClient)
    client.chat = AsyncMock(return_value=(reply, 100, 50))
    return client


async def test_answer_calls_llm_when_chunk_found() -> None:
    result = await answer(
        "What damage does the Megashark do?",
        _STATE,
        anthropic=_mock_anthropic("It deals 25 damage."),
        retrieval=_mock_retrieval([_CHUNK]),
        faq_prompt=_PROMPT,
    )

    assert isinstance(result, BotAnswer)
    assert result.answer == "It deals 25 damage."
    assert result.routing == RoutingDecision.faq
    assert len(result.source_chunks) == 1


async def test_answer_skips_llm_when_zero_chunks() -> None:
    mock_chat = AsyncMock(return_value=("...", 10, 5))
    client = MagicMock(spec=AnthropicClient)
    client.chat = mock_chat

    result = await answer(
        "Something obscure with no matching wiki page.",
        _STATE,
        anthropic=client,
        retrieval=_mock_retrieval([]),
        faq_prompt=_PROMPT,
    )

    mock_chat.assert_not_awaited()
    assert result.answer == _NO_CHUNK_ANSWER
    assert result.source_chunks == []
    assert result.routing == RoutingDecision.faq


async def test_answer_builds_chunk_ref_correctly() -> None:
    result = await answer(
        "What damage does the Megashark do?",
        _STATE,
        anthropic=_mock_anthropic(),
        retrieval=_mock_retrieval([_CHUNK]),
        faq_prompt=_PROMPT,
    )

    assert len(result.source_chunks) == 1
    ref = result.source_chunks[0]
    assert ref.page_title == "Megashark"
    assert ref.section == "stats"
    assert ref.source_url == "https://terraria.wiki.gg/wiki/Megashark"
    assert ref.score == pytest.approx(0.92)


async def test_answer_threads_parent_span() -> None:
    """faq.answer span is opened on parent; threaded to retrieval and chat."""
    mock_parent = MagicMock()
    mock_faq_span = MagicMock()
    mock_parent.span.return_value = mock_faq_span

    mock_retrieve = AsyncMock(return_value=[_CHUNK])
    mock_pipeline = MagicMock(spec=RetrievalPipeline)
    mock_pipeline.retrieve = mock_retrieve

    mock_chat = AsyncMock(return_value=("It deals 25 damage.", 100, 50))
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.chat = mock_chat

    await answer(
        "What damage does the Megashark do?",
        _STATE,
        anthropic=mock_client,
        retrieval=mock_pipeline,
        faq_prompt=_PROMPT,
        parent_span=mock_parent,
    )

    # span opened on parent with correct name and input
    mock_parent.span.assert_called_once_with(
        name="faq.answer",
        input={"query": "What damage does the Megashark do?"},
    )
    # faq span threaded to retrieval
    _, ret_kwargs = mock_retrieve.call_args
    assert ret_kwargs["parent_observation"] is mock_faq_span
    # faq span threaded to chat
    _, chat_kwargs = mock_chat.call_args
    assert chat_kwargs["parent"] is mock_faq_span
    assert chat_kwargs["span_name"] == "faq.llm"
    # span is closed
    mock_faq_span.end.assert_called_once()
