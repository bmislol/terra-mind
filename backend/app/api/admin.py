"""Operator-only admin routes (Phase 5.2).

Both are **cross-tenant operator views**, gated by ``require_operator`` (a
player-role token → 403). They are intentionally **not** RLS-scoped: `tenants`
and `audit_log` have no RLS policy and the service sets no tenant context. This
is the deliberate counterpart to per-tenant CONTENT (sessions/messages/
preferences), which is fail-closed DB RLS — two data categories, two controls
(the answer to "an operator sees all tenants, but RLS blocks cross-tenant reads —
how?": RLS protects per-tenant content; admin data is app-role-gated, not RLS'd).

Deferred (P-018/P-019, DECISIONS): `GET /admin/versions/check` (live-wiki
compare) and `POST /admin/rerag` (the `build_corpus.py` script is the must-have,
ARCH §10/§7 — the button is stretch).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_operator
from app.domain.admin import AuditEntry, TenantSummary
from app.services import admin as admin_svc
from app.services.auth import AccessContext

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(
    request: Request,
    _auth: AccessContext = Depends(require_operator),
) -> list[TenantSummary]:
    """Operator-only: every tenant (id / email / is_guest / created_at)."""
    return await admin_svc.list_tenants(request.app.state.session_factory)


@admin_router.get("/audit-log", response_model=list[AuditEntry])
async def list_audit_log(
    request: Request,
    _auth: AccessContext = Depends(require_operator),
) -> list[AuditEntry]:
    """Operator-only: recent audit events (`tenant.erased` / `auth.login` /
    `session.revoked`, SECURITY §6)."""
    return await admin_svc.list_audit(request.app.state.session_factory)
