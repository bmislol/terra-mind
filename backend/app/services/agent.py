from __future__ import annotations

import logging
from typing import Any

from anthropic.types import TextBlock

from app.agent.class_detection import DEFAULT_CLASSIFIER, ItemClassifier
from app.agent.graph import build_agent_graph
from app.core.prompts import LoadedPrompts
from app.domain.bot import BotAnswer, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.pipeline import RetrievalPipeline

_log = logging.getLogger(__name__)

_FALLBACK_MESSAGE = (
    "I ran into a problem while researching your question. "
    "Try rephrasing or asking about a specific item, boss, or mechanic."
)


async def answer(
    query: str,
    state: StatePayload,
    *,
    anthropic: AnthropicClient,
    retrieval: RetrievalPipeline,
    prompts: LoadedPrompts,
    classifier: ItemClassifier = DEFAULT_CLASSIFIER,
    parent_span: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
) -> BotAnswer:
    """Run the bounded LangGraph agent for state-dependent questions.

    Opens an agent.run span as child of parent_span when tracing is active.
    On any unhandled exception from the graph, logs and returns a safe
    fallback BotAnswer so the endpoint never surfaces a 500.
    """
    span = None
    if parent_span is not None:
        span = parent_span.span(name="agent.run", input={"query": query})

    try:
        graph = build_agent_graph(retrieval, anthropic, prompts, classifier)
        initial_state = {
            "messages": [{"role": "user", "content": query}],
            "chunks_seen": [],
            "iteration_count": 0,
            "state_payload": state,
        }
        result = await graph.ainvoke(initial_state)

        last_msg = result["messages"][-1]
        content = last_msg.get("content", [])
        answer_text = _FALLBACK_MESSAGE
        if isinstance(content, list):
            for block in content:
                if isinstance(block, TextBlock):
                    answer_text = block.text
                    break
        elif isinstance(content, str):
            answer_text = content

        bot_answer = BotAnswer(
            answer=answer_text,
            source_chunks=result["chunks_seen"],
            routing=RoutingDecision.agent,
        )
    except Exception:
        _log.exception("agent graph failed for query=%r", query)
        bot_answer = BotAnswer(
            answer=_FALLBACK_MESSAGE,
            source_chunks=[],
            routing=RoutingDecision.agent,
        )

    if span is not None:
        span.end(output={"answer": bot_answer.answer[:200]})

    return bot_answer
