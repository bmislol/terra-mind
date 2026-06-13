"""Unit tests for AnthropicClient.  No real API calls — mock injected via _client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.infra.anthropic import AnthropicClient, ChatMessage, ToolParam
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


# ── chat_with_tools tests ─────────────────────────────────────────────────────

_TOOLS: list[ToolParam] = [
    {
        "name": "query_wiki",
        "description": "Search the Terraria wiki.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]


def _make_tool_use_mock_client(
    stop_reason: str = "tool_use",
    tool_id: str = "tool_id_1",
    tool_name: str = "query_wiki",
    tool_input: dict[str, object] | None = None,
    input_tokens: int = 40,
    output_tokens: int = 15,
) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        ToolUseBlock(
            id=tool_id,
            name=tool_name,
            input=tool_input or {"query": "Skeletron boss fight"},
            type="tool_use",
        )
    ]
    mock_response.stop_reason = stop_reason
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


async def test_chat_with_tools_returns_tool_use_block_and_stop_reason() -> None:
    """stop_reason='tool_use' path: content_blocks contains a ToolUseBlock."""
    client = AnthropicClient(
        api_key="sk-ant-fake",
        _client=_make_tool_use_mock_client(stop_reason="tool_use"),
    )
    blocks, stop_reason, in_tok, out_tok = await client.chat_with_tools(
        messages=_MESSAGES,
        model="claude-haiku-4-5",
        system="You are an agent.",
        tools=_TOOLS,
    )

    assert stop_reason == "tool_use"
    assert len(blocks) == 1
    block = blocks[0]
    assert isinstance(block, ToolUseBlock)
    assert block.name == "query_wiki"
    assert block.id == "tool_id_1"
    assert in_tok == 40
    assert out_tok == 15


async def test_chat_with_tools_end_turn_returns_text_block() -> None:
    """stop_reason='end_turn' path: content_blocks contains a TextBlock."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [TextBlock(text="Final answer.", type="text")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage.input_tokens = 50
    mock_response.usage.output_tokens = 20
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    client = AnthropicClient(api_key="sk-ant-fake", _client=mock_client)
    blocks, stop_reason, in_tok, out_tok = await client.chat_with_tools(
        messages=_MESSAGES,
        model="claude-haiku-4-5",
        system="You are an agent.",
        tools=_TOOLS,
    )

    assert stop_reason == "end_turn"
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextBlock)
    assert blocks[0].text == "Final answer."
    assert in_tok == 50
    assert out_tok == 20


async def test_chat_with_tools_generation_event_includes_stop_reason() -> None:
    """Generation event carries stop_reason in metadata; output is '[tool_use]'."""
    mock_parent = MagicMock()
    mock_create = AsyncMock()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        ToolUseBlock(id="x1", name="query_wiki", input={"query": "q"}, type="tool_use")
    ]
    mock_response.stop_reason = "tool_use"
    mock_response.usage.input_tokens = 30
    mock_response.usage.output_tokens = 5
    mock_client.messages.create = mock_create
    mock_create.return_value = mock_response

    client = AnthropicClient(api_key="sk-ant-fake", _client=mock_client)
    await client.chat_with_tools(
        messages=_MESSAGES,
        model="claude-haiku-4-5",
        system="agent",
        tools=_TOOLS,
        span_name="agent.llm",
        parent=mock_parent,
    )

    mock_parent.generation.assert_called_once()
    kw = mock_parent.generation.call_args.kwargs
    assert kw["name"] == "agent.llm"
    assert kw["output"] == "[tool_use]"
    assert kw["metadata"]["stop_reason"] == "tool_use"
    assert kw["metadata"]["latency_ms"] >= 0
    assert kw["usage_details"] == {"input": 30, "output": 5}
