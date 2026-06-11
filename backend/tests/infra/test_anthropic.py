"""Unit tests for AnthropicClient.  No real API calls — mock injected via _client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import TextBlock

from app.infra.anthropic import AnthropicClient, ChatMessage
from app.infra.tracing import current_trace_var


def _make_mock_client(
    text: str = "faq",
    input_tokens: int = 20,
    output_tokens: int = 1,
) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [TextBlock(text=text, type="text")]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


_MESSAGES: list[ChatMessage] = [
    {"role": "user", "content": "What damage does the Megashark do?"}
]


async def test_chat_returns_text_and_tokens() -> None:
    client = AnthropicClient(
        api_key="sk-ant-fake",
        _client=_make_mock_client("The Megashark deals 25 damage.", 30, 10),
    )
    text, in_tok, out_tok = await client.chat(
        messages=_MESSAGES,
        model="claude-haiku-4-5",
        system="test",
    )
    assert text == "The Megashark deals 25 damage."
    assert in_tok == 30
    assert out_tok == 10


async def test_chat_calls_generation_on_parent() -> None:
    mock_parent = MagicMock()
    client = AnthropicClient(
        api_key="sk-ant-fake",
        _client=_make_mock_client("faq", 20, 1),
    )

    await client.chat(
        messages=_MESSAGES,
        model="claude-haiku-4-5",
        system="test system",
        span_name="test.gen",
        parent=mock_parent,
    )

    mock_parent.generation.assert_called_once()
    kw = mock_parent.generation.call_args.kwargs
    assert kw["name"] == "test.gen"
    assert kw["model"] == "claude-haiku-4-5"
    assert kw["output"] == "faq"
    assert kw["usage_details"] == {"input": 20, "output": 1}
    assert "start_time" in kw
    assert "end_time" in kw
    assert kw["metadata"]["latency_ms"] >= 0


async def test_chat_raises_on_non_text_block() -> None:
    mock_client = MagicMock()
    non_text_block = MagicMock()  # not a TextBlock → isinstance check fails
    mock_response = MagicMock()
    mock_response.content = [non_text_block]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    client = AnthropicClient(api_key="sk-ant-fake", _client=mock_client)
    with pytest.raises(RuntimeError, match="Expected TextBlock"):
        await client.chat(
            messages=_MESSAGES,
            model="claude-haiku-4-5",
            system="test",
        )


async def test_chat_no_parent_no_current_trace_skips_generation() -> None:
    """When no parent is given and current_trace_var is unset, no generation emitted."""
    mock_client = _make_mock_client()
    # Ensure contextvar is clear for this test.
    token = current_trace_var.set(None)
    try:
        client = AnthropicClient(api_key="sk-ant-fake", _client=mock_client)
        text, in_tok, out_tok = await client.chat(
            messages=_MESSAGES,
            model="claude-haiku-4-5",
            system="test",
        )
    finally:
        current_trace_var.reset(token)

    assert text == "faq"
    assert in_tok == 20
    assert out_tok == 1
