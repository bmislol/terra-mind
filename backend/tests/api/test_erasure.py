"""Right-to-erasure proof (Phase 4.1b) — the methodological MIRROR of the
isolation proof.

- test_rls_isolation connects as the **non-superuser** `terramind_app` so RLS
  *engages* and proves rows are HIDDEN across tenants.
- this test verifies from the **owner** (superuser) connection so RLS is
  *bypassed* and proves the rows are PHYSICALLY GONE — a same-context query
  would return 0 for the erased tenant whether deletion worked OR RLS masked
  them, so only an RLS-bypassing view distinguishes deletion from masking.

Two real tenants write via the real `/bot/ask` path; A erases via `DELETE /me`;
the owner connection then shows A's rows gone and B's surviving.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import psycopg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.class_detection import ItemClassifier
from app.api.bot import bot_router
from app.api.me import me_router
from app.core.prompts import LoadedPrompts
from app.db.models import Tenant
from app.domain.bot import BotAnswer, RoutingDecision
from app.infra.anthropic import AnthropicClient
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets
from app.rag.pipeline import RetrievalPipeline

_KEY = "test-erasure-signing-key-0123456789"


def _build_app(
    factory: async_sessionmaker[AsyncSession],
    redis: fakeredis.aioredis.FakeRedis,
) -> FastAPI:
    app = FastAPI()
    app.include_router(bot_router)
    app.include_router(me_router)
    app.state.anthropic = MagicMock(spec=AnthropicClient)
    app.state.retrieval_pipeline = MagicMock(spec=RetrievalPipeline)
    app.state.item_classifier = MagicMock(spec=ItemClassifier)
    app.state.session_factory = factory
    app.state.redis = redis
    app.state.secrets = AppSecrets(anthropic_api_key="sk-ant-x", jwt_signing_key=_KEY)
    app.state.prompts = LoadedPrompts(
        router="r", faq_answer="f", agent_system="a", class_fallback="c"
    )
    return app


async def _seed_tenant(
    factory: async_sessionmaker[AsyncSession], *, is_guest: bool = False
) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            Tenant(
                id=tenant_id,
                email=None if is_guest else f"{tenant_id}@example.com",
                hashed_password=None if is_guest else "x",
                is_active=True,
                is_guest=is_guest,
            )
        )
        await session.commit()
    return tenant_id


def _header(tenant_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(tenant_id=tenant_id, role="player", signing_key=_KEY)
    return {"Authorization": f"Bearer {token}"}


async def _ask(app: FastAPI, tenant_id: uuid.UUID, message: str) -> None:
    canned = BotAnswer(answer="ok", source_chunks=[], routing=RoutingDecision.faq)
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.faq),
        ),
        patch("app.api.bot.faq_svc.answer", AsyncMock(return_value=canned)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask", json={"message": message}, headers=_header(tenant_id)
            )
    assert resp.status_code == 200


def _owner_count(owner_dsn: str, table: str, tenant_id: uuid.UUID) -> int:
    """Count rows for a tenant from the OWNER connection (RLS bypassed)."""
    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute(
            f"SELECT count(*) FROM {table} WHERE tenant_id = %s",  # noqa: S608
            (str(tenant_id),),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _audit_for(
    owner_dsn: str, tenant_id: uuid.UUID
) -> list[tuple[str, dict[str, object]]]:
    with psycopg.connect(owner_dsn) as conn:
        rows = conn.execute(
            "SELECT action, metadata FROM audit_log WHERE actor = %s",
            (str(tenant_id),),
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


async def _erasure_flow(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
    *,
    erasing_is_guest: bool,
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    tenant_a = await _seed_tenant(app_session_factory, is_guest=erasing_is_guest)
    tenant_b = await _seed_tenant(app_session_factory)

    await _ask(app, tenant_a, "A question")
    await _ask(app, tenant_b, "B question")

    # Rows exist before erasure (owner view — the "affected count > 0" premise).
    assert _owner_count(owner_sync_dsn, "messages", tenant_a) == 2
    assert _owner_count(owner_sync_dsn, "sessions", tenant_a) == 1

    # Tenant A erases their own data.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete("/me", headers=_header(tenant_a))
    assert resp.status_code == 204

    # ── PRIMARY PROOF (owner connection, RLS bypassed): A's rows PHYSICALLY gone,
    #    B's SURVIVE. Not masking — the owner sees all rows regardless of RLS. ──
    assert _owner_count(owner_sync_dsn, "messages", tenant_a) == 0
    assert _owner_count(owner_sync_dsn, "sessions", tenant_a) == 0
    assert _owner_count(owner_sync_dsn, "messages", tenant_b) == 2
    assert _owner_count(owner_sync_dsn, "sessions", tenant_b) == 1

    # Redis: A's history keys gone, B's present.
    assert await redis.keys(f"session:{tenant_a}:*") == []
    assert await redis.keys(f"session:{tenant_b}:*") != []

    # Audit: a tenant.erased row for A, with the deleted-row count (> 0).
    # tenant.erased row for A, with deleted_rows = 2 messages + 1 session.
    audit = _audit_for(owner_sync_dsn, tenant_a)
    assert any(
        action == "tenant.erased" and meta["deleted_rows"] == 3
        for action, meta in audit
    )

    await redis.aclose()


async def test_delete_me_physically_erases_a_keeps_b(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    await _erasure_flow(app_session_factory, owner_sync_dsn, erasing_is_guest=False)


async def test_delete_me_erases_a_guest_tenant_too(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    """A guest that asks for erasure gets it — same purge as a player."""
    await _erasure_flow(app_session_factory, owner_sync_dsn, erasing_is_guest=True)


async def test_delete_me_retains_preferences(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
) -> None:
    """D-032: erasure purges conversation CONTENT but KEEPS preferences (account
    config). The account + prefs outlive a content erasure — proven from the
    owner connection (RLS bypassed) AND a live GET that still returns them.
    This is the assertion D-032's 5.1 extension lacked (Phase 6.2)."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    tenant_a = await _seed_tenant(app_session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        patched = await client.patch(
            "/me/preferences",
            json={"selected_version": "1.4.4.9"},
            headers=_header(tenant_a),
        )
        assert patched.status_code == 200
    await _ask(app, tenant_a, "A question")  # conversation content to erase

    # Both the pref row and the content rows exist before erasure (owner view).
    assert _owner_count(owner_sync_dsn, "tenant_preferences", tenant_a) == 1
    assert _owner_count(owner_sync_dsn, "messages", tenant_a) == 2

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete("/me", headers=_header(tenant_a))
        assert resp.status_code == 204
        # The account survives → prefs are still readable after erasing content.
        prefs = await client.get("/me/preferences", headers=_header(tenant_a))
    assert prefs.status_code == 200
    assert prefs.json()["selected_version"] == "1.4.4.9"

    # Content gone, preferences RETAINED (owner view, RLS bypassed).
    assert _owner_count(owner_sync_dsn, "messages", tenant_a) == 0
    assert _owner_count(owner_sync_dsn, "sessions", tenant_a) == 0
    assert _owner_count(owner_sync_dsn, "tenant_preferences", tenant_a) == 1

    await redis.aclose()
