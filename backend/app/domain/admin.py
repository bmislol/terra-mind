"""Operator-view domain models (Phase 5.2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenantSummary(BaseModel):
    id: UUID
    email: str | None
    is_guest: bool
    created_at: datetime


class AuditEntry(BaseModel):
    action: str
    actor: UUID
    target: str | None
    metadata: dict[str, object]
    created_at: datetime


class ReragStartRequest(BaseModel):
    """Body for POST /admin/rerag — the corpus version to re-embed."""

    version: str = Field(min_length=1)


class ReragStartResponse(BaseModel):
    """Returned by POST /admin/rerag — the enqueued job's id + initial status."""

    job_id: UUID
    status: str


class ReragStatus(BaseModel):
    """Returned by GET /admin/rerag/status/{job_id} — the durable rerag_jobs row,
    with the freshest live progress (stage/done/total) overlaid from Redis."""

    job_id: UUID
    version: str
    status: str  # queued | running | succeeded | failed
    stage: str
    done: int
    total: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
