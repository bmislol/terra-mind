"""Message-row writes (under the caller's RLS context).

``tenant_id`` is denormalized on each row so the RLS policy needs no join; the
service passes the context tenant explicitly, and the WITH CHECK predicate
(D-030) rejects any row whose ``tenant_id`` doesn't match the set context.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message


async def add_message(
    session: AsyncSession,
    *,
    session_id: UUID,
    tenant_id: UUID,
    role: str,
    content: str,
) -> None:
    """Insert one message row. Caller owns the transaction + RLS context."""
    session.add(
        Message(
            session_id=session_id,
            tenant_id=tenant_id,
            role=role,
            content=content,
        )
    )


async def delete_for_current_tenant(session: AsyncSession) -> int:
    """DELETE the rows visible under the set RLS context; returns the count.

    No WHERE clause: the policy (D-030) scopes the DELETE to the context tenant
    — and if the context were unset it would delete nothing (fail-closed).
    """
    result = cast("CursorResult[Any]", await session.execute(delete(Message)))
    return result.rowcount
