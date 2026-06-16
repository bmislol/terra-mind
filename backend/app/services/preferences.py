"""Preference read/update orchestration (Phase 5.1).

Mirrors the erasure service's RLS pattern: open a session → set the tenant
context → call the repo (RLS-scoped) → commit. The endpoint passes only the
authenticated ``tenant_id``; the service owns the context + transaction.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.preferences import Preferences
from app.repositories import preferences as preferences_repo
from app.services.rls import set_tenant_context


async def get_preferences(
    *, tenant_id: UUID, session_factory: async_sessionmaker[AsyncSession]
) -> Preferences:
    """Read the tenant's stored preferences (defaults when no row exists)."""
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        stored = await preferences_repo.get_for_current_tenant(session)
    return Preferences.model_validate(stored)


async def update_preferences(
    *,
    tenant_id: UUID,
    preferences: Preferences,
    session_factory: async_sessionmaker[AsyncSession],
) -> Preferences:
    """Persist (upsert) the tenant's preferences under their RLS context."""
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        await preferences_repo.upsert_for_current_tenant(
            session, tenant_id=tenant_id, preferences=preferences.model_dump()
        )
        await session.commit()
    return preferences
