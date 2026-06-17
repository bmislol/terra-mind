"""Operator admin views — cross-tenant reads + the require_operator gate (5.2).

Connects as the non-superuser `terramind_app` (app_session_factory): proves the
operator reads `tenants`/`audit_log` across all tenants *without* a tenant
context (those tables have no RLS), while a player-role token is blocked (403).
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin import admin_router
from app.db.models import Tenant
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets
from app.repositories.audit import write_audit

_KEY = "test-admin-signing-key-0123456789"


def _build_app(
    factory: async_sessionmaker[AsyncSession],
    redis: fakeredis.aioredis.FakeRedis,
) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.state.session_factory = factory
    app.state.redis = redis  # require_access_token (under require_operator) checks it
    app.state.secrets = AppSecrets(anthropic_api_key="sk-ant-x", jwt_signing_key=_KEY)
    return app


async def _seed_tenant(
    factory: async_sessionmaker[AsyncSession], *, is_guest: bool = False
) -> uuid.UUID:
    tid = uuid.uuid4()
    async with factory() as session:
        session.add(
            Tenant(
                id=tid,
                email=None if is_guest else f"{tid}@x.dev",
                hashed_password=None if is_guest else "x",
                is_active=True,
                is_guest=is_guest,
            )
        )
        await session.commit()
    return tid


def _header(tenant_id: uuid.UUID, role: str) -> dict[str, str]:
    token = create_access_token(tenant_id=tenant_id, role=role, signing_key=_KEY)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_tenants_operator_sees_all_player_403(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    a = await _seed_tenant(app_session_factory)
    b = await _seed_tenant(app_session_factory, is_guest=True)
    op = await _seed_tenant(app_session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Operator sees ALL tenants (cross-tenant, no context).
        resp = await client.get("/admin/tenants", headers=_header(op, "operator"))
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert {str(a), str(b), str(op)} <= ids

        # Player → 403.
        resp = await client.get("/admin/tenants", headers=_header(a, "player"))
        assert resp.status_code == 403
    await redis.aclose()


async def test_admin_audit_operator_sees_player_403(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    actor = await _seed_tenant(app_session_factory)
    async with app_session_factory() as session:
        await write_audit(
            session, actor=actor, action="auth.login", target=str(actor), meta={"x": 1}
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/admin/audit-log", headers=_header(actor, "operator"))
        assert resp.status_code == 200
        assert "auth.login" in [e["action"] for e in resp.json()]

        # Player → 403.
        resp = await client.get("/admin/audit-log", headers=_header(actor, "player"))
        assert resp.status_code == 403
    await redis.aclose()
