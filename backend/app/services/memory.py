"""Session-memory orchestration for /bot/ask (ARCH §4, §8).

The **service** sets the RLS tenant context (D-030) and owns the transaction
boundaries; the endpoint only passes the authenticated tenant_id, and the
repositories run the SQL under the context. Content is redacted before it
crosses into either store (SECURITY §7).

Two short transactions per turn — the multi-second agent/FAQ call runs between
them with **no DB transaction held** (a `SET LOCAL` context is per-transaction,
re-set each time; holding a connection across the LLM call would be wrong):

  txn 1 (resolve_session) → [router + agent/FAQ, no DB] → txn 2 (record_turn).
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.redaction import redact
from app.memory.short_term import append_message
from app.repositories.messages import add_message
from app.repositories.sessions import get_or_create_session
from app.services.rls import set_tenant_context


async def resolve_session(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    session_id: UUID | None,
    game_version: str,
) -> UUID:
    """txn 1: set RLS context → get/create the session row → commit. Returns its id."""
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        resolved = await get_or_create_session(
            session,
            tenant_id=tenant_id,
            session_id=session_id,
            game_version=game_version,
        )
        await session.commit()
    return resolved


async def record_turn(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    tenant_id: UUID,
    session_id: UUID,
    user_message: str,
    assistant_message: str,
) -> None:
    """txn 2: persist the user+assistant turn to Postgres (under RLS) and Redis.

    Redacted before both writes. The RLS context is re-set here because the set
    in txn 1 ended at that commit (SET LOCAL is transaction-local).
    """
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        await add_message(
            session,
            session_id=session_id,
            tenant_id=tenant_id,
            role="user",
            content=redact(user_message),
        )
        await add_message(
            session,
            session_id=session_id,
            tenant_id=tenant_id,
            role="assistant",
            content=redact(assistant_message),
        )
        await session.commit()

    # Redis short-term cache — append_message redacts at its own boundary.
    await append_message(
        redis,
        tenant_id=tenant_id,
        session_id=session_id,
        role="user",
        content=user_message,
    )
    await append_message(
        redis,
        tenant_id=tenant_id,
        session_id=session_id,
        role="assistant",
        content=assistant_message,
    )
