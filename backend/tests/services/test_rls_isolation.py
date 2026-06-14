"""The headline tenant-isolation proof (Phase 4.1b) — "tenant isolation is the
security story" (CLAUDE §4.3) as a CI-gated fact. Phase 7.1 re-demos this live.

Two REAL tenants drive the REAL `/bot/ask` write path (commit 2 — not direct
inserts), against the real pgvector Postgres connected as the **non-superuser
`terramind_app`** role (a superuser bypasses RLS and would prove nothing). The
PRIMARY proof is the Postgres/RLS layer: under tenant B's context a raw SELECT
of `messages` returns exactly B's rows and **none** of A's — Postgres-enforced,
not application filtering. Redis key-namespacing isolation is shown too, as
belt-and-suspenders.

This test reads like the 7.1 demo script.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.class_detection import ItemClassifier
from app.api.bot import bot_router
from app.core.prompts import LoadedPrompts
from app.db.models import Tenant
from app.domain.bot import BotAnswer, RoutingDecision
from app.infra.anthropic import AnthropicClient
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets
from app.memory.short_term import get_history
from app.rag.pipeline import RetrievalPipeline
from app.services.rls import set_tenant_context

_KEY = "test-rls-isolation-signing-key-0123456789"


def _build_app(
    factory: async_sessionmaker[AsyncSession],
    redis: fakeredis.aioredis.FakeRedis,
) -> FastAPI:
    app = FastAPI()
    app.include_router(bot_router)
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


async def _ask(
    app: FastAPI, tenant_id: uuid.UUID, message: str, answer: str
) -> uuid.UUID:
    """POST /bot/ask as *tenant_id* (real write path; mocked routing/answer)."""
    canned = BotAnswer(answer=answer, source_chunks=[], routing=RoutingDecision.faq)
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
    return uuid.UUID(resp.json()["session_id"])


async def _messages_under(
    factory: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str]]:
    """Raw SELECT of messages under *tenant_id*'s RLS context, oldest→newest."""
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, role, content FROM messages ORDER BY created_at"
                )
            )
        ).all()
    return [(r.tenant_id, r.role, r.content) for r in rows]


async def test_two_tenant_isolation_through_the_real_bot_ask_path(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = _build_app(app_session_factory, redis)
    tenant_a = await _seed_tenant(app_session_factory)
    tenant_b = await _seed_tenant(app_session_factory)

    # Tenant A asks → A's session + message rows written under A's context.
    a_session = await _ask(app, tenant_a, "A question", "A answer")

    # ── PRIMARY PROOF: under B's context, B sees ZERO of A's rows (Postgres). ──
    assert await _messages_under(app_session_factory, tenant_b) == []

    # Tenant B asks → B's own rows; now both tenants' data coexists.
    b_session = await _ask(app, tenant_b, "B question", "B answer")

    a_view = await _messages_under(app_session_factory, tenant_a)
    b_view = await _messages_under(app_session_factory, tenant_b)

    # Each context sees exactly its own rows — by tenant, count, and content.
    assert {row[0] for row in a_view} == {tenant_a}
    assert [(row[1], row[2]) for row in a_view] == [
        ("user", "A question"),
        ("assistant", "A answer"),
    ]
    assert {row[0] for row in b_view} == {tenant_b}
    assert [(row[1], row[2]) for row in b_view] == [
        ("user", "B question"),
        ("assistant", "B answer"),
    ]

    # ── Belt-and-suspenders: Redis key-namespacing also isolates. ──
    a_hist = await get_history(redis, tenant_id=tenant_a, session_id=a_session)
    b_hist = await get_history(redis, tenant_id=tenant_b, session_id=b_session)
    assert [m["content"] for m in a_hist] == ["A question", "A answer"]
    assert [m["content"] for m in b_hist] == ["B question", "B answer"]
    # B's namespace cannot reach A's session history (different key).
    assert await get_history(redis, tenant_id=tenant_b, session_id=a_session) == []

    await redis.aclose()
