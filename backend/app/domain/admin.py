"""Operator-view domain models (Phase 5.2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
