"""Unit tests for app/agent/graph.py.

All LLM calls are replaced by pre-baked AsyncMock returns so no real Anthropic
calls are made.  The mock returns (content_blocks, stop_reason, in_tok, out_tok)
matching the chat_with_tools() signature.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from anthropic.types import TextBlock, ToolUseBlock
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import MAX_ITERATIONS, build_agent_graph
from app.core.prompts import LoadedPrompts
from app.domain.bot import StatePayload
from app.rag.pipeline import RetrievalPipeline

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _prompts() -> LoadedPrompts:
    return LoadedPrompts(
        router="You are a router.",
        faq_answer="You are a FAQ assistant.",
        agent_system=(
            "You are a Terraria survival advisor with tools. Answer in 3-5 sentences."
        ),
        class_fallback="Infer the class. One word.",
    )


def _text_block(text: str = "Here is your answer.") -> TextBlock:
    return TextBlock(text=text, type="text")


def _tool_use_block(
    tool_id: str = "tu_001",
    name: str = "query_wiki",
    inp: dict | None = None,  # type: ignore[type-arg]
) -> ToolUseBlock:
    return ToolUseBlock(
        id=tool_id,
        name=name,
        input=inp or {"query": "Megashark damage"},
        type="tool_use",
    )


def _end_turn_response(text: str = "Here is your answer.") -> tuple:  # type: ignore[type-arg]
    return ([_text_block(text)], "end_turn", 100, 50)


def _tool_use_response(
    tool_id: str = "tu_001",
    name: str = "query_wiki",
    inp: dict | None = None,  # type: ignore[type-arg]
) -> tuple:  # type: ignore[type-arg]
    return ([_tool_use_block(tool_id, name, inp)], "tool_use", 120, 30)


def _make_graph(
    mock_chat_with_tools: AsyncMock,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    mock_anthropic = MagicMock()
    mock_anthropic.chat_with_tools = mock_chat_with_tools
    # analyze_loadout on empty-gear state triggers the llm_classify fallback
    # (commit 4), which calls .chat — stub it so multi-tool tests don't hang.
    mock_anthropic.chat = AsyncMock(return_value=("unknown", 0, 0))
    mock_retrieval = MagicMock(spec=RetrievalPipeline)
    mock_retrieval.retrieve = AsyncMock(return_value=[])
    return build_agent_graph(mock_retrieval, mock_anthropic, _prompts())


def _initial_state(question: str = "What damage does the Megashark deal?") -> dict:  # type: ignore[type-arg]
    return {
        "messages": [{"role": "user", "content": question}],
        "chunks_seen": [],
        "iteration_count": 0,
        "state_payload": StatePayload(),
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_graph_immediate_end_turn_returns_answer() -> None:
    """LLM returns end_turn on first call → graph terminates immediately."""
    mock_cwt = AsyncMock(
        return_value=_end_turn_response("The Megashark deals 25 base damage.")
    )
    graph = _make_graph(mock_cwt)

    result = await graph.ainvoke(_initial_state())

    mock_cwt.assert_awaited_once()
    messages = result["messages"]
    last = messages[-1]
    assert last["role"] == "assistant"
    content = last["content"]
    assert isinstance(content, list)
    assert any(isinstance(b, TextBlock) and "Megashark" in b.text for b in content)


async def test_graph_single_tool_call_then_end_turn() -> None:
    """LLM requests one tool → tools execute → LLM returns final answer."""
    mock_cwt = AsyncMock(
        side_effect=[
            _tool_use_response("tu_001", "query_wiki", {"query": "Megashark stats"}),
            _end_turn_response("The Megashark deals 25 base damage."),
        ]
    )
    graph = _make_graph(mock_cwt)

    result = await graph.ainvoke(_initial_state())

    assert mock_cwt.await_count == 2
    # iteration_count incremented once
    assert result["iteration_count"] == 1
    last = result["messages"][-1]
    assert last["role"] == "assistant"


async def test_graph_multiple_tool_iterations() -> None:
    """LLM requests tools twice before ending — iteration_count tracks correctly."""
    mock_cwt = AsyncMock(
        side_effect=[
            _tool_use_response("tu_001", "query_wiki", {"query": "Megashark"}),
            _tool_use_response("tu_002", "analyze_loadout", {}),
            _end_turn_response("Based on your loadout and the Megashark stats…"),
        ]
    )
    graph = _make_graph(mock_cwt)

    result = await graph.ainvoke(_initial_state("What should I do next?"))

    assert mock_cwt.await_count == 3
    assert result["iteration_count"] == 2
    last = result["messages"][-1]
    assert last["role"] == "assistant"


async def test_graph_cap_triggers_synthesize() -> None:
    """After MAX_ITERATIONS tool calls the cap node runs instead of plan."""
    # Always respond with tool_use to force cap
    mock_cwt = AsyncMock(
        side_effect=(
            [
                _tool_use_response(f"tu_{i:03d}", "query_wiki", {"query": "x"})
                for i in range(MAX_ITERATIONS)
            ]
            + [_end_turn_response("Synthesized answer under cap.")]
        )
    )
    graph = _make_graph(mock_cwt)

    result = await graph.ainvoke(_initial_state("Never stop asking questions"))

    # MAX_ITERATIONS tool responses + 1 final synthesize call
    assert mock_cwt.await_count == MAX_ITERATIONS + 1
    assert result["iteration_count"] == MAX_ITERATIONS
    last = result["messages"][-1]
    assert last["role"] == "assistant"
