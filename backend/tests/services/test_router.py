"""Unit tests for app/services/router.py.  No real API calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.domain.bot import RoutingDecision
from app.infra.anthropic import AnthropicClient
from app.services.router import classify


def _mock_anthropic(reply: str, in_tok: int = 20, out_tok: int = 1) -> AnthropicClient:
    """Return an AnthropicClient whose chat() returns the given reply."""
    client = MagicMock(spec=AnthropicClient)
    client.chat = AsyncMock(return_value=(reply, in_tok, out_tok))
    return client


_PROMPT = "You are a router."


async def test_classify_returns_faq() -> None:
    decision = await classify(
        "What damage does the Megashark do?",
        anthropic=_mock_anthropic("faq"),
        router_prompt=_PROMPT,
    )
    assert decision == RoutingDecision.faq


async def test_classify_returns_agent() -> None:
    decision = await classify(
        "Why do I keep dying to Skeletron?",
        anthropic=_mock_anthropic("agent"),
        router_prompt=_PROMPT,
    )
    assert decision == RoutingDecision.agent


async def test_classify_normalises_whitespace_and_case() -> None:
    """Leading/trailing whitespace and uppercase are handled gracefully."""
    decision = await classify(
        "What is the recipe for Iron Sword?",
        anthropic=_mock_anthropic("  FAQ\n"),
        router_prompt=_PROMPT,
    )
    assert decision == RoutingDecision.faq


async def test_classify_defaults_to_agent_on_unknown_reply() -> None:
    """Any reply other than 'faq' (normalised) falls back to agent."""
    decision = await classify(
        "Tell me about Terraria.",
        anthropic=_mock_anthropic("UNKNOWN_WORD"),
        router_prompt=_PROMPT,
    )
    assert decision == RoutingDecision.agent


async def test_classify_defaults_to_agent_on_empty_reply() -> None:
    decision = await classify(
        "Tell me about Terraria.",
        anthropic=_mock_anthropic(""),
        router_prompt=_PROMPT,
    )
    assert decision == RoutingDecision.agent


async def test_classify_opens_span_on_parent_and_passes_to_chat() -> None:
    """parent_span.span() is called; the returned span is passed to chat()."""
    mock_parent = MagicMock()
    mock_span = MagicMock()
    mock_parent.span.return_value = mock_span

    # Hold a direct reference to the AsyncMock so mypy sees call_args on MagicMock.
    mock_chat = AsyncMock(return_value=("faq", 20, 1))
    client = MagicMock(spec=AnthropicClient)
    client.chat = mock_chat

    await classify(
        "What damage does the Megashark do?",
        anthropic=client,
        router_prompt=_PROMPT,
        parent_span=mock_parent,
    )

    mock_parent.span.assert_called_once_with(
        name="router.classify",
        input={"query": "What damage does the Megashark do?"},
    )
    # chat() must receive the span as its parent
    _, call_kwargs = mock_chat.call_args
    assert call_kwargs["parent"] is mock_span
    assert call_kwargs["span_name"] == "router.llm"
    # span is closed after the decision
    mock_span.end.assert_called_once()


async def test_classify_no_parent_span_skips_span_creation() -> None:
    """When parent_span is None, no span is opened; chat() receives parent=None."""
    mock_chat = AsyncMock(return_value=("agent", 20, 1))
    client = MagicMock(spec=AnthropicClient)
    client.chat = mock_chat

    decision = await classify(
        "What should I do next?",
        anthropic=client,
        router_prompt=_PROMPT,
        parent_span=None,
    )

    assert decision == RoutingDecision.agent
    _, call_kwargs = mock_chat.call_args
    assert call_kwargs["parent"] is None
