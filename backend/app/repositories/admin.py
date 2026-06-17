"""Operator (cross-tenant) reads — tenants list + audit log.

These read tables that have **no RLS policy** (`tenants` = identity table;
`audit_log` = cross-tenant by design, D-017), so there is **no tenant context to
set** and the non-superuser `terramind_app` role reads every row (it holds
`SELECT` on both, initial migration). Authorization is the `require_operator`
gate at the route — a player never reaches here. This is the deliberate
counterpart to the per-tenant CONTENT tables (sessions/messages/preferences),
which ARE fail-closed RLS + `set_tenant_context`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Tenant


async def list_tenants(session: AsyncSession) -> list[Tenant]:
    """All tenant rows, oldest first. No tenant context (tenants has no RLS)."""
    result = await session.execute(select(Tenant).order_by(Tenant.created_at))
    return list(result.scalars().all())


async def list_audit(session: AsyncSession, *, limit: int = 100) -> list[AuditLog]:
    """Most-recent audit rows. No tenant context (audit_log has no RLS, D-017)."""
    result = await session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
