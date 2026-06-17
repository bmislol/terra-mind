"""GET/PATCH /me/preferences + the RLS isolation proof (Phase 5.1, Option 2).

The isolation test is the point of putting preferences in their own RLS table
(not a tenants column): it connects via the **non-superuser** ``terramind_app``
so RLS engages, and verifies from the **owner** connection (RLS bypassed) that
A's and B's prefs are physically distinct rows — B's token can neither read nor
overwrite A's. Falsifiable: with RLS off, B's GET would surface A's value.
"""

from __future__ import annotations

import uuid
from typing import Any

import fakeredis.aioredis
import psycopg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.me import me_router
from app.db.models import Tenant
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets

_KEY = "test-prefs-signing-key-0123456789"


def _build_app(
    factory: async_sessionmaker[AsyncSession],
    redis: fakeredis.aioredis.FakeRedis,
) -> FastAPI:
    app = FastAPI()
    app.include_router(me_router)
    app.state.session_factory = factory
    app.state.redis = redis  # require_access_token checks the denylist
    app.state.secrets = AppSecrets(anthropic_api_key="sk-ant-x", jwt_signing_key=_KEY)
    return app


async def _seed_tenant(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
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


def _header(tenant_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(tenant_id=tenant_id, role="player", signing_key=_KEY)
    return {"Authorization": f"Bearer {token}"}


def _owner_prefs(owner_dsn: str, tenant_id: uuid.UUID) -> dict[str, Any] | None:
    """Read a tenant's prefs from the OWNER connection (RLS bypassed)."""
    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute(
            "SELECT preferences FROM tenant_preferences WHERE tenant_id = %s",
            (str(tenant_id),),
        ).fetchone()
    return row[0] if row is not None else None


async def test_get_defaults_then_patch_persists(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    tenant = await _seed_tenant(app_session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # GET with no row yet → defaults.
        resp = await client.get("/me/preferences", headers=_header(tenant))
        assert resp.status_code == 200
        assert resp.json() == {"selected_version": None}

        # PATCH persists.
        resp = await client.patch(
            "/me/preferences",
            json={"selected_version": "1.4.4.9"},
            headers=_header(tenant),
        )
        assert resp.status_code == 200
        assert resp.json() == {"selected_version": "1.4.4.9"}

        # GET reflects the saved state (the "persists across reload" round-trip).
        resp = await client.get("/me/preferences", headers=_header(tenant))
        assert resp.json() == {"selected_version": "1.4.4.9"}
    await redis.aclose()


async def test_prefs_rls_isolation_b_cannot_touch_a(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    tenant_a = await _seed_tenant(app_session_factory)
    tenant_b = await _seed_tenant(app_session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # A saves a preference.
        await client.patch(
            "/me/preferences",
            json={"selected_version": "1.4.4.9"},
            headers=_header(tenant_a),
        )
        # B reads — sees only its OWN defaults, never A's value.
        resp = await client.get("/me/preferences", headers=_header(tenant_b))
        assert resp.json() == {"selected_version": None}
        # B writes its own — must not collide with or overwrite A's row.
        resp = await client.patch(
            "/me/preferences",
            json={"selected_version": "1.3.5.3"},
            headers=_header(tenant_b),
        )
        assert resp.status_code == 200

    # Owner view (RLS bypassed): two distinct rows, each with its own value.
    assert _owner_prefs(owner_sync_dsn, tenant_a) == {"selected_version": "1.4.4.9"}
    assert _owner_prefs(owner_sync_dsn, tenant_b) == {"selected_version": "1.3.5.3"}
    await redis.aclose()
