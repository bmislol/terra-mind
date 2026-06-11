from __future__ import annotations

from typing import Any

from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient, ChatMessage
from app.rag.pipeline import RetrievalPipeline

_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 512
_NO_CHUNK_ANSWER = "I don't have enough information to answer that specifically."


async def answer(
    query: str,
    state: StatePayload,
    *,
    anthropic: AnthropicClient,
    retrieval: RetrievalPipeline,
    faq_prompt: str,
    parent_span: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
) -> BotAnswer:
    """Answer *query* via single-chunk retrieval followed by Haiku synthesis.

    Opens a ``faq.answer`` span as a child of *parent_span* (when provided)
    and threads it through both the retrieval call and the LLM call so the
    Langfuse trace tree nests correctly:
        faq.answer > rag.retrieve
        faq.answer > faq.llm (generation)
    """
    faq_span: Any = None
    if parent_span is not None:
        faq_span = parent_span.span(
            name="faq.answer",
            input={"query": query},
        )

    chunks = await retrieval.retrieve(
        query,
        game_version=state.game_version,
        k=1,
        parent_observation=faq_span,
    )

    if not chunks:
        if faq_span is not None:
            faq_span.end(output={"answer": _NO_CHUNK_ANSWER})
        return BotAnswer(
            answer=_NO_CHUNK_ANSWER,
            source_chunks=[],
            routing=RoutingDecision.faq,
        )

    chunk = chunks[0]
    user_message = (
        f"Wiki excerpt from {chunk.page_title} (§{chunk.section}):\n"
        f"{chunk.content}\n\n"
        f"Player question: {query}"
    )
    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]

    text, _, _ = await anthropic.chat(
        messages=messages,
        model=_MODEL,
        system=faq_prompt,
        max_tokens=_MAX_TOKENS,
        span_name="faq.llm",
        parent=faq_span,
    )

    if faq_span is not None:
        faq_span.end(output={"answer": text[:100]})

    return BotAnswer(
        answer=text,
        source_chunks=[
            ChunkRef(
                page_title=chunk.page_title,
                section=chunk.section,
                source_url=chunk.source_url,
                score=chunk.score,
            )
        ],
        routing=RoutingDecision.faq,
    )
