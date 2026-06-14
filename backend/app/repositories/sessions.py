"""Session-row reads/writes (under the caller's RLS context).

Runs inside a transaction whose tenant context the *service* has already set
(ARCH §4 — repositories never set the RLS context). An existing session row is
visible only if it belongs to the context tenant (RLS), so cross-tenant
session_ids are simply not found.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session as SessionRow


async def get_or_create_session(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID | None,
    game_version: str,
) -> UUID:
    """Return an existing session's id (touching ``last_active_at``) or create one."""
    if session_id is not None:
        existing = (
            await session.execute(
                select(SessionRow.id).where(SessionRow.id == session_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            await session.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(last_active_at=func.now())
            )
            return session_id

    new_id = session_id or uuid4()
    session.add(SessionRow(id=new_id, tenant_id=tenant_id, game_version=game_version))
    return new_id


async def delete_for_current_tenant(session: AsyncSession) -> int:
    """DELETE the session rows visible under the set RLS context; returns count.

    Run after the tenant's messages are deleted (messages FK→sessions). The
    policy (D-030) scopes the DELETE to the context tenant; unset → deletes none.
    """
    result = cast("CursorResult[Any]", await session.execute(delete(SessionRow)))
    return result.rowcount
