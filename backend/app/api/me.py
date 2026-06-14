"""Self-service tenant routes (Phase 4.1b).

DELETE /me — right to erasure: the authenticated tenant deletes their own data
(messages, sessions, Redis history) + a tenant.erased audit row. The endpoint
only extracts tenant_id and calls the erasure service (ARCH §4 — the service
sets the RLS context and owns the deletes).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import require_access_token
from app.services import erasure as erasure_svc
from app.services.auth import AccessContext

me_router = APIRouter(tags=["me"])


@me_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def erase_me(
    request: Request,
    auth: AccessContext = Depends(require_access_token),
) -> None:
    await erasure_svc.erase_tenant(
        tenant_id=auth.tenant_id,
        session_factory=request.app.state.session_factory,
        redis=request.app.state.redis,
    )
