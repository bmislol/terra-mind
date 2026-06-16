"""Self-service tenant routes (Phase 4.1b).

DELETE /me — right to erasure: the authenticated tenant deletes their own data
(messages, sessions, Redis history) + a tenant.erased audit row. The endpoint
only extracts tenant_id and calls the erasure service (ARCH §4 — the service
sets the RLS context and owns the deletes).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import require_access_token
from app.domain.preferences import Preferences
from app.services import erasure as erasure_svc
from app.services import preferences as preferences_svc
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


@me_router.get("/me/preferences", response_model=Preferences)
async def get_preferences(
    request: Request,
    auth: AccessContext = Depends(require_access_token),
) -> Preferences:
    """The authenticated tenant's stored preferences (defaults if unset).

    DEFERRAL (DECISIONS P-017): `selected_version` is stored + round-tripped but
    is NOT consumed by /bot/ask retrieval — that path uses the mod's live
    `state.game_version`. Wiring a stored preference into retrieval is a separate,
    larger change, deferred. 5.1 preferences = storage + round-trip only.
    """
    return await preferences_svc.get_preferences(
        tenant_id=auth.tenant_id,
        session_factory=request.app.state.session_factory,
    )


@me_router.patch("/me/preferences", response_model=Preferences)
async def update_preferences(
    request: Request,
    body: Preferences,
    auth: AccessContext = Depends(require_access_token),
) -> Preferences:
    """Persist the authenticated tenant's preferences (RLS-scoped upsert)."""
    return await preferences_svc.update_preferences(
        tenant_id=auth.tenant_id,
        preferences=body,
        session_factory=request.app.state.session_factory,
    )
