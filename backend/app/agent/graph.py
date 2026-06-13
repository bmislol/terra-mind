from __future__ import annotations

from typing import Any, Literal

from anthropic.types import ToolUseBlock
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.state import AgentState
from app.agent.tools import (
    ALL_TOOLS,
    analyze_loadout,
    query_wiki,
    suggest_next_boss,
    tool_result_content,
)
from app.core.prompts import LoadedPrompts
from app.domain.bot import ChunkRef
from app.infra.anthropic import AnthropicClient
from app.rag.pipeline import RetrievalPipeline

MAX_ITERATIONS = 5
_MODEL = "claude-haiku-4-5"


def build_agent_graph(
    retrieval: RetrievalPipeline,
    anthropic_client: AnthropicClient,
    prompts: LoadedPrompts,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    """Return a compiled LangGraph agent that handles hard, state-dependent questions.

    retrieval, anthropic_client, and prompts are captured in closures — they are
    infrastructure dependencies, not serializable state.
    """

    async def plan(state: AgentState) -> dict[str, Any]:
        """Call the LLM with tools; append the assistant turn to messages."""
        blocks, _, _, _ = await anthropic_client.chat_with_tools(
            messages=state["messages"],
            model=_MODEL,
            system=prompts.agent_system,
            tools=ALL_TOOLS,
        )
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": blocks}
        return {"messages": [assistant_msg]}

    async def execute_tools(state: AgentState) -> dict[str, Any]:
        """Dispatch tool calls in last assistant message; append results."""
        last_msg = state["messages"][-1]
        content: Any = last_msg.get("content", [])

        tool_results: list[dict[str, Any]] = []
        new_chunks: list[ChunkRef] = []
        sp = state["state_payload"]

        for block in content if isinstance(content, list) else []:
            if not isinstance(block, ToolUseBlock):
                continue

            name = block.name
            inp: dict[str, Any] = block.input

            payload: Any
            if name == "query_wiki":
                result = await query_wiki(
                    inp["query"],
                    game_version=sp.game_version,
                    k=int(inp.get("k", 5)),
                    retrieval=retrieval,
                )
                for r in result:
                    new_chunks.append(
                        ChunkRef(
                            page_title=r["page_title"],
                            section=r["section"],
                            source_url=r["source_url"],
                            score=float(r["score"]),
                        )
                    )
                payload = [{k: v for k, v in r.items() if k != "score"} for r in result]
            elif name == "analyze_loadout":
                payload = analyze_loadout(sp)
            elif name == "suggest_next_boss":
                payload = suggest_next_boss(sp)
            else:
                payload = {"error": f"unknown tool: {name}"}

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result_content(payload),
                }
            )

        tool_msg: dict[str, Any] = {"role": "user", "content": tool_results}
        return {
            "messages": [tool_msg],
            "chunks_seen": new_chunks,
            "iteration_count": state["iteration_count"] + 1,
        }

    async def synthesize_cap(state: AgentState) -> dict[str, Any]:
        """Call the LLM one final time when MAX_ITERATIONS is reached."""
        cap_notice: dict[str, Any] = {
            "role": "user",
            "content": (
                "You have reached the tool-call limit. "
                "Synthesize the best answer you can from the tool results so far."
            ),
        }
        blocks, _, _, _ = await anthropic_client.chat_with_tools(
            messages=state["messages"] + [cap_notice],
            model=_MODEL,
            system=prompts.agent_system,
            tools=[],
        )
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": blocks}
        return {"messages": [cap_notice, assistant_msg]}

    def _route_plan(
        state: AgentState,
    ) -> Literal["execute_tools", "__end__"]:
        last = state["messages"][-1]
        content: Any = last.get("content", [])
        for block in content if isinstance(content, list) else []:
            if isinstance(block, ToolUseBlock):
                return "execute_tools"
        return "__end__"

    def _route_execute(state: AgentState) -> Literal["plan", "synthesize_cap"]:
        if state["iteration_count"] >= MAX_ITERATIONS:
            return "synthesize_cap"
        return "plan"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("synthesize_cap", synthesize_cap)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan", _route_plan, {"execute_tools": "execute_tools", END: END}
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route_execute,
        {"plan": "plan", "synthesize_cap": "synthesize_cap"},
    )
    graph.add_edge("synthesize_cap", END)

    return graph.compile()
