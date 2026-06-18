"""Guardrail orchestration for /bot/ask (Phase 6.1, D-034).

Wraps the ``app/guardrails/`` filter so the api/ layer never invokes the
Tier-2 LLM-judge directly (the LLM call stays in the service layer), and writes
the ``guardrail.blocked`` audit row. Audit is operator/cross-tenant with **no
RLS** (D-017, like ``auth.login``/``tenant.erased``), so it needs no tenant
context — only ``require_access_token`` reached the handler.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.guardrails import Verdict
from app.guardrails import check_input as _check_input
from app.guardrails import check_output as _check_output
from app.infra.anthropic import AnthropicClient
from app.repositories.audit import write_audit


async def check_input(
    message: str,
    *,
    anthropic: AnthropicClient,
    judge_prompt: str,
    parent_span: Any = None,
) -> Verdict:
    return await _check_input(
        message, anthropic=anthropic, judge_prompt=judge_prompt, parent_span=parent_span
    )


async def check_output(
    answer: str,
    *,
    anthropic: AnthropicClient,
    judge_prompt: str,
    parent_span: Any = None,
) -> Verdict:
    return await _check_output(
        answer, anthropic=anthropic, judge_prompt=judge_prompt, parent_span=parent_span
    )


async def record_block(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    verdict: Verdict,
    surface: str,  # "input" | "output"
) -> None:
    """Write a ``guardrail.blocked`` audit row (no tenant context — audit_log
    has no RLS, D-017). ``surface`` is the target; the category/reason are meta."""
    async with session_factory() as session:
        await write_audit(
            session,
            actor=tenant_id,
            action="guardrail.blocked",
            target=surface,
            meta={"category": str(verdict.category), "reason": verdict.reason},
        )
        await session.commit()
