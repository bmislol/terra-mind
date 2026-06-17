"""Corpus versions route (Phase 5.1).

GET /versions — the shared corpus's available game versions. **Public**: it's
shared, version-tagged corpus metadata (D-005), not tenant data, so no token is
needed to populate the portal's version dropdown. Currently typically one
(1.4.4.9, D-016).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services import versions as versions_svc

versions_router = APIRouter(tags=["versions"])


class VersionsResponse(BaseModel):
    versions: list[str]


@versions_router.get("/versions", response_model=VersionsResponse)
async def get_versions(request: Request) -> VersionsResponse:
    versions = await versions_svc.list_versions(request.app.state.session_factory)
    return VersionsResponse(versions=versions)
