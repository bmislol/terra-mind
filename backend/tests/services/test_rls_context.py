"""RLS tenant-context mechanism proof (Phase 4.1a) — the security kernel.

Runs against the real pgvector Postgres connected as the **non-superuser**
``terramind_app`` role (a superuser would bypass RLS and prove nothing). This
proves the mechanism `set_tenant_context` relies on; Phase 4.1b expands it into
the full two-tenant product isolation proof (`test_rls_isolation.py`).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Session as SessionRow
from app.db.models import Tenant
from app.services.rls import set_tenant_context


async def _make_tenant(
    factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Create a tenant row (tenants has no RLS) and return its id."""
    tenant_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            Tenant(
                id=tenant_id,
                email=f"{tenant_id}@example.com",
                hashed_password="x",
                is_active=True,
            )
        )
        await session.commit()
    return tenant_id


async def test_rls_scopes_rows_to_the_set_tenant_context(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = await _make_tenant(app_session_factory)
    tenant_b = await _make_tenant(app_session_factory)

    # Write a sessions row under tenant A's context.
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a)
        session.add(SessionRow(tenant_id=tenant_a, game_version="1.4.4.9"))
        await session.commit()

    # Under tenant B's context, A's row is invisible (Postgres-enforced).
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b)
        rows = (await session.execute(select(SessionRow))).scalars().all()
    assert rows == []

    # Under tenant A's context, A's row is visible.
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a)
        rows = (await session.execute(select(SessionRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_a


async def test_uncontexted_connection_sees_zero_rows_fail_closed(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No set_config → current_setting is NULL → the policy denies all rows.

    This also proves the transaction-local setting does not leak: the prior
    test's contexted writes are invisible to a fresh, uncontexted connection.
    """
    tenant_a = await _make_tenant(app_session_factory)
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a)
        session.add(SessionRow(tenant_id=tenant_a, game_version="1.4.4.9"))
        await session.commit()

    async with app_session_factory() as session:
        rows = (await session.execute(select(SessionRow))).scalars().all()
    assert rows == []


async def test_cross_tenant_insert_is_rejected_by_with_check(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Under tenant A's context, inserting a row for tenant B is blocked."""
    tenant_a = await _make_tenant(app_session_factory)
    tenant_b = await _make_tenant(app_session_factory)

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a)
        session.add(SessionRow(tenant_id=tenant_b, game_version="1.4.4.9"))
        with pytest.raises(DBAPIError):
            await session.commit()
