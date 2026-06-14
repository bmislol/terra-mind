from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.infra.tracing import current_trace_var
from app.services import agent as agent_svc
from app.services import faq as faq_svc
from app.services import router as router_svc

bot_router = APIRouter(prefix="/bot", tags=["bot"])


class AskRequest(BaseModel):
    message: str
    state: StatePayload | None = None


class AskResponse(BaseModel):
    answer: str
    source_chunks: list[ChunkRef]
    routing: str


@bot_router.post("/ask", response_model=AskResponse)
async def ask(request: Request, body: AskRequest) -> AskResponse:
    state = body.state or StatePayload()

    trace = current_trace_var.get()
    bot_span = None
    if trace is not None:
        bot_span = trace.span(
            name="bot.ask",
            input={"message": body.message},
        )

    decision = await router_svc.classify(
        body.message,
        anthropic=request.app.state.anthropic,
        router_prompt=request.app.state.prompts.router,
        parent_span=bot_span,
    )

    bot_answer: BotAnswer
    if decision == RoutingDecision.faq:
        bot_answer = await faq_svc.answer(
            body.message,
            state,
            anthropic=request.app.state.anthropic,
            retrieval=request.app.state.retrieval_pipeline,
            faq_prompt=request.app.state.prompts.faq_answer,
            parent_span=bot_span,
        )
    else:
        bot_answer = await agent_svc.answer(
            body.message,
            state,
            anthropic=request.app.state.anthropic,
            retrieval=request.app.state.retrieval_pipeline,
            prompts=request.app.state.prompts,
            classifier=request.app.state.item_classifier,
            parent_span=bot_span,
        )

    if bot_span is not None:
        bot_span.end(output={"routing": bot_answer.routing})

    return AskResponse(
        answer=bot_answer.answer,
        source_chunks=bot_answer.source_chunks,
        routing=bot_answer.routing,
    )
