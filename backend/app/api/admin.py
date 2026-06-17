"""Operator-only admin routes (Phase 5.2).

Both are **cross-tenant operator views**, gated by ``require_operator`` (a
player-role token → 403). They are intentionally **not** RLS-scoped: `tenants`
and `audit_log` have no RLS policy and the service sets no tenant context. This
is the deliberate counterpart to per-tenant CONTENT (sessions/messages/
preferences), which is fail-closed DB RLS — two data categories, two controls
(the answer to "an operator sees all tenants, but RLS blocks cross-tenant reads —
how?": RLS protects per-tenant content; admin data is app-role-gated, not RLS'd).

Deferred (P-018, DECISIONS): `GET /admin/versions/check` (live-wiki compare).
`POST /admin/rerag` is now built as a background job (D-033, reverses P-019).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_operator
from app.domain.admin import (
    AuditEntry,
    ReragStartRequest,
    ReragStartResponse,
    ReragStatus,
    TenantSummary,
)
from app.services import admin as admin_svc
from app.services import rerag as rerag_svc
from app.services.auth import AccessContext
from app.services.rerag import ReragInProgress

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
    `session.revoked` / `corpus.reragged`, SECURITY §6)."""
    return await admin_svc.list_audit(request.app.state.session_factory)


@admin_router.post(
    "/rerag", response_model=ReragStartResponse, status_code=status.HTTP_202_ACCEPTED
)
async def start_rerag(
    body: ReragStartRequest,
    request: Request,
    auth: AccessContext = Depends(require_operator),
) -> ReragStartResponse:
    """Operator-only: start a background re-rag of the given corpus version.

    Returns the job id (202). If a re-rag is already running, **409** — the
    single-job guard (no queue, D-033). Poll `GET /admin/rerag/status/{job_id}`.
    """
    try:
        return await rerag_svc.start_rerag(
            request.app.state.session_factory,
            request.app.state.rerag_queue,
            version=body.version,
            requested_by=auth.tenant_id,
        )
    except ReragInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="RERAG_ALREADY_RUNNING"
        ) from exc


@admin_router.get("/rerag/status/{job_id}", response_model=ReragStatus)
async def rerag_status(
    job_id: UUID,
    request: Request,
    _auth: AccessContext = Depends(require_operator),
) -> ReragStatus:
    """Operator-only: a re-rag job's durable status + live progress."""
    result = await rerag_svc.get_rerag_status(
        request.app.state.session_factory, request.app.state.rerag_queue, job_id
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="RERAG_JOB_NOT_FOUND"
        )
    return result
