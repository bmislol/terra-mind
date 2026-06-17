"""Operator admin reads (Phase 5.2).

Cross-tenant operator views. Unlike tenant-scoped services (memory/erasure/
preferences), these **do not** call ``set_tenant_context`` — the operator spans
all tenants, and `tenants`/`audit_log` carry no RLS policy. The authorization
boundary is ``require_operator`` at the route (a player → 403).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin import AuditEntry, TenantSummary
from app.repositories import admin as admin_repo


async def list_tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[TenantSummary]:
    async with session_factory() as session:
        rows = await admin_repo.list_tenants(session)
    return [
        TenantSummary(
            id=t.id, email=t.email, is_guest=t.is_guest, created_at=t.created_at
        )
        for t in rows
    ]


async def list_audit(
    session_factory: async_sessionmaker[AsyncSession], *, limit: int = 100
) -> list[AuditEntry]:
    async with session_factory() as session:
        rows = await admin_repo.list_audit(session, limit=limit)
    return [
        AuditEntry(
            action=a.action,
            actor=a.actor,
            target=a.target,
            metadata=a.meta,
            created_at=a.created_at,
        )
        for a in rows
    ]
