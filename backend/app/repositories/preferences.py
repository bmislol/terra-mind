"""Preference-row reads/writes (under the caller's RLS context).

``tenant_preferences`` carries the same fail-closed ``tenant_isolation`` policy
as sessions/messages (D-030 NULLIF form). The service sets the context; these
queries then scope to that tenant automatically (and to nothing, fail-closed, if
the context were unset).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantPreferences


async def get_for_current_tenant(session: AsyncSession) -> dict[str, Any]:
    """The context tenant's stored preferences JSONB, or ``{}`` if no row yet.

    No WHERE clause: RLS scopes the SELECT to the context tenant. ``{}`` means
    "no row → defaults".
    """
    stored = (
        await session.execute(select(TenantPreferences.preferences))
    ).scalar_one_or_none()
    return dict(stored) if stored is not None else {}


async def upsert_for_current_tenant(
    session: AsyncSession, *, tenant_id: UUID, preferences: dict[str, Any]
) -> None:
    """Insert-or-update the context tenant's preferences row.

    ``tenant_id`` is set explicitly so the INSERT satisfies the RLS WITH CHECK
    (the USING predicate doubles as WITH CHECK): a row whose ``tenant_id`` is not
    the set context is rejected.
    """
    stmt = pg_insert(TenantPreferences).values(
        tenant_id=tenant_id, preferences=preferences
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id"],
        set_={"preferences": preferences, "updated_at": func.now()},
    )
    await session.execute(stmt)
