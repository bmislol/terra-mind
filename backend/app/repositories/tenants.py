"""Tenant-table writes that bypass fastapi-users (guests).

Guests are ephemeral tenants with NULL email/password — they never go through
the fastapi-users register/user-manager path (which requires credentials). The
underlying columns are nullable (initial migration); the Tenant ORM model
inherits non-optional typing from fastapi-users for the *player* path, so this
constructs a guest by omitting email/hashed_password (→ NULL at the DB).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant


async def create_guest(session: AsyncSession, *, ttl_seconds: int) -> Tenant:
    """Add a guest tenant row (NULL email/password). Caller commits.

    ``id`` is set in Python so it's available without a flush/refresh.
    """
    guest = Tenant(
        id=uuid4(),
        is_guest=True,
        is_active=True,
        guest_expires_at=datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds),
    )
    session.add(guest)
    return guest
