"""Audit-log writes (SECURITY §6).

audit_log is append-only and intentionally NOT RLS-scoped (cross-tenant,
operator-gated at the service layer — D-017), so writes need no tenant context.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
    actor: UUID,
    action: str,
    target: str | None = None,
    meta: dict[str, object] | None = None,
) -> None:
    """Insert one audit row. Caller owns the transaction/commit."""
    session.add(AuditLog(actor=actor, action=action, target=target, meta=meta or {}))
