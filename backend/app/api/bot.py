from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import require_access_token
from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.guardrails import REFUSAL_MESSAGE
from app.infra.tracing import current_trace_var
from app.services import agent as agent_svc
from app.services import faq as faq_svc
from app.services import guardrails as guardrails_svc
from app.services import memory as memory_svc
from app.services import router as router_svc
from app.services.auth import AccessContext

bot_router = APIRouter(prefix="/bot", tags=["bot"])


class AskRequest(BaseModel):
    message: str
    state: StatePayload | None = None
    session_id: UUID | None = None


class AskResponse(BaseModel):
    answer: str
    source_chunks: list[ChunkRef]
    routing: str
    session_id: UUID


@bot_router.post("/ask", response_model=AskResponse)
async def ask(
    request: Request,
    body: AskRequest,
    auth: AccessContext = Depends(require_access_token),
) -> AskResponse:
    state = body.state or StatePayload()

    # txn 1 — the service sets the RLS context and resolves/creates the session.
    session_id = await memory_svc.resolve_session(
        session_factory=request.app.state.session_factory,
        tenant_id=auth.tenant_id,
        session_id=body.session_id,
        game_version=state.game_version,
    )

    trace = current_trace_var.get()
    bot_span = None
    if trace is not None:
        bot_span = trace.span(
            name="bot.ask",
            input={"message": body.message, "tenant_id": str(auth.tenant_id)},
        )

    # ── Input guardrail (ARCH §5 step 4) — before routing/LLM ──────────────────
    # A block skips routing+answer entirely: refuse, audit, record the turn.
    input_verdict = await guardrails_svc.check_input(
        body.message,
        anthropic=request.app.state.anthropic,
        judge_prompt=request.app.state.prompts.guardrail_judge,
        parent_span=bot_span,
    )
    if input_verdict.blocked:
        await guardrails_svc.record_block(
            request.app.state.session_factory,
            tenant_id=auth.tenant_id,
            verdict=input_verdict,
            surface="input",
        )
        await memory_svc.record_turn(
            session_factory=request.app.state.session_factory,
            redis=request.app.state.redis,
            tenant_id=auth.tenant_id,
            session_id=session_id,
            user_message=body.message,
            assistant_message=REFUSAL_MESSAGE,
        )
        if bot_span is not None:
            bot_span.end(
                output={"routing": "blocked", "category": str(input_verdict.category)}
            )
        return AskResponse(
            answer=REFUSAL_MESSAGE,
            source_chunks=[],
            routing="blocked",
            session_id=session_id,
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

    # txn 2 — persist the turn (Postgres under RLS + Redis), redacted. The agent
    # call above ran with no DB transaction held; the service re-sets the context.
    # ── Output guardrail (ARCH §5 step 9) — before the reply leaves ────────────
    output_verdict = await guardrails_svc.check_output(
        bot_answer.answer,
        anthropic=request.app.state.anthropic,
        judge_prompt=request.app.state.prompts.guardrail_judge,
        parent_span=bot_span,
    )
    answer_text: str = bot_answer.answer
    source_chunks: list[ChunkRef] = bot_answer.source_chunks
    routing_label: str = bot_answer.routing
    if output_verdict.blocked:
        await guardrails_svc.record_block(
            request.app.state.session_factory,
            tenant_id=auth.tenant_id,
            verdict=output_verdict,
            surface="output",
        )
        answer_text = REFUSAL_MESSAGE
        source_chunks = []
        routing_label = "blocked"

    await memory_svc.record_turn(
        session_factory=request.app.state.session_factory,
        redis=request.app.state.redis,
        tenant_id=auth.tenant_id,
        session_id=session_id,
        user_message=body.message,
        assistant_message=answer_text,
    )

    if bot_span is not None:
        bot_span.end(output={"routing": routing_label})

    return AskResponse(
        answer=answer_text,
        source_chunks=source_chunks,
        routing=routing_label,
        session_id=session_id,
    )
