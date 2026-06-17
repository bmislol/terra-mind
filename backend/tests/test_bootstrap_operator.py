"""Operator bootstrap (RUNBOOK §3) — create, idempotent re-run, promote."""

from __future__ import annotations

import uuid

import psycopg
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Tenant
from app.entrypoints.bootstrap_operator import bootstrap_operator
from app.infra.auth import UserManager


def _is_superuser(owner_dsn: str, email: str) -> bool | None:
    """Read is_superuser from the OWNER connection (tenants has no RLS anyway)."""
    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute(
            "SELECT is_superuser FROM tenants WHERE email = %s", (email,)
        ).fetchone()
    return None if row is None else bool(row[0])


async def test_bootstrap_creates_then_idempotent(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    created = await bootstrap_operator(
        email="op@x.dev", password="pw-123456", session_factory=app_session_factory
    )
    assert created is True
    assert _is_superuser(owner_sync_dsn, "op@x.dev") is True

    # The bootstrapped password actually verifies → login will work.
    async with app_session_factory() as session:
        user_db: SQLAlchemyUserDatabase[Tenant, uuid.UUID] = SQLAlchemyUserDatabase(
            session, Tenant
        )
        user = await user_db.get_by_email("op@x.dev")
        assert user is not None
        um = UserManager(user_db, token_secret="x")
        valid, _ = um.password_helper.verify_and_update(
            "pw-123456", user.hashed_password
        )
        assert valid is True

    # Re-run → promote path (already operator), not a new create.
    again = await bootstrap_operator(
        email="op@x.dev", password="pw-123456", session_factory=app_session_factory
    )
    assert again is False
    assert _is_superuser(owner_sync_dsn, "op@x.dev") is True


async def test_bootstrap_promotes_existing_player(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    async with app_session_factory() as session:
        session.add(
            Tenant(
                id=uuid.uuid4(),
                email="player@x.dev",
                hashed_password="x",
                is_active=True,
                is_superuser=False,
            )
        )
        await session.commit()
    assert _is_superuser(owner_sync_dsn, "player@x.dev") is False

    created = await bootstrap_operator(
        email="player@x.dev", password="ignored", session_factory=app_session_factory
    )
    assert created is False  # promoted, not created
    assert _is_superuser(owner_sync_dsn, "player@x.dev") is True
