"""Endpoint tests for POST /bot/ask.

Auth is real (genuine minted access tokens through `require_access_token`). The
routing services are patched at the bot module boundary, but the **memory write
path is real** (Phase 4.1b): the handler resolves/creates a session and persists
the turn to Postgres (under RLS) + Redis, so these run against the testcontainer
Postgres + fakeredis — no skip/mock shortcut bypasses the RLS write.
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
from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient
from app.infra.jwt_tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.infra.vault import AppSecrets
from app.memory.denylist import deny
from app.rag.pipeline import RetrievalPipeline
from app.services.rls import set_tenant_context

_SIGNING_KEY = "test-bot-ask-signing-key-0123456789"


def _make_app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    """Minimal FastAPI with bot_router + real session_factory + fakeredis."""
    test_app = FastAPI()
    test_app.include_router(bot_router)
    test_app.state.anthropic = MagicMock(spec=AnthropicClient)
    test_app.state.retrieval_pipeline = MagicMock(spec=RetrievalPipeline)
    test_app.state.item_classifier = MagicMock(spec=ItemClassifier)
    test_app.state.session_factory = session_factory
    test_app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    test_app.state.secrets = AppSecrets(
        anthropic_api_key="sk-ant-not-real", jwt_signing_key=_SIGNING_KEY
    )
    test_app.state.prompts = LoadedPrompts(
        router="You are a router.",
        faq_answer="You are a FAQ assistant.",
        agent_system="You are an agent.",
        class_fallback="You are a class classifier.",
    )
    return test_app


async def _seed_tenant(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    """Insert a player tenant (FK target for sessions.tenant_id) and return its id."""
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


def _auth_header(tenant_id: uuid.UUID, role: str = "player") -> dict[str, str]:
    token = create_access_token(
        tenant_id=tenant_id, role=role, signing_key=_SIGNING_KEY
    )
    return {"Authorization": f"Bearer {token}"}


_FAQ_ANSWER = BotAnswer(
    answer="The Megashark deals 25 base damage.",
    source_chunks=[
        ChunkRef(
            page_title="Megashark",
            section="stats",
            source_url="https://terraria.wiki.gg/wiki/Megashark",
            score=0.92,
        )
    ],
    routing=RoutingDecision.faq,
)

_AGENT_ANSWER = BotAnswer(
    answer="Try Fossil armor and keep moving — you're a ranger in early pre-hardmode.",
    source_chunks=[],
    routing=RoutingDecision.agent,
)


async def test_ask_faq_question_returns_200_with_routing_faq(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(app_session_factory)
    app = _make_app(app_session_factory)
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.faq),
        ),
        patch("app.api.bot.faq_svc.answer", AsyncMock(return_value=_FAQ_ANSWER)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask",
                json={"message": "What damage does the Megashark do?"},
                headers=_auth_header(tenant_id),
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["routing"] == "faq"
    assert data["answer"] == "The Megashark deals 25 base damage."
    assert len(data["source_chunks"]) == 1
    uuid.UUID(data["session_id"])  # a session was created and returned


async def test_ask_agent_question_returns_200_with_routing_agent(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await _seed_tenant(app_session_factory)
    app = _make_app(app_session_factory)
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.agent),
        ),
        patch("app.api.bot.agent_svc.answer", AsyncMock(return_value=_AGENT_ANSWER)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask",
                json={"message": "Why do I keep dying to Skeletron?"},
                headers=_auth_header(tenant_id),
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["routing"] == "agent"
    assert data["source_chunks"] == []


async def test_ask_persists_turn_under_the_authed_tenant(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The real write path: the user+assistant turn lands in messages (owner view)."""
    tenant_id = await _seed_tenant(app_session_factory)
    app = _make_app(app_session_factory)
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.faq),
        ),
        patch("app.api.bot.faq_svc.answer", AsyncMock(return_value=_FAQ_ANSWER)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask",
                json={"message": "What damage does the Megashark do?"},
                headers=_auth_header(tenant_id),
            )
    session_id = resp.json()["session_id"]

    # Verify under the tenant's own RLS context (uncontexted would see 0 rows —
    # the rows are written under context, RLS hides them otherwise).
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        rows = (
            await session.execute(
                text("SELECT role, content FROM messages ORDER BY created_at")
            )
        ).all()
        count = (
            await session.execute(
                text("SELECT count(*) FROM sessions WHERE id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[1].content == "The Megashark deals 25 base damage."
    assert count == 1


async def test_ask_default_state_uses_default_game_version(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """body.state=None → faq.answer receives StatePayload(game_version='1.4.4.9')."""
    tenant_id = await _seed_tenant(app_session_factory)
    mock_faq = AsyncMock(return_value=_FAQ_ANSWER)
    app = _make_app(app_session_factory)
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.faq),
        ),
        patch("app.api.bot.faq_svc.answer", mock_faq),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask",
                json={"message": "What damage?"},
                headers=_auth_header(tenant_id),
            )

    assert resp.status_code == 200
    state_arg: StatePayload = mock_faq.call_args.args[1]
    assert state_arg.game_version == "1.4.4.9"


async def test_ask_missing_message_returns_422(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = _make_app(app_session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Valid token (random tenant — body validation fails before any DB write).
        resp = await client.post(
            "/bot/ask", json={}, headers=_auth_header(uuid.uuid4())
        )
    assert resp.status_code == 422


# ── Auth gate (no DB reached — 401 before the handler) ────────────────────────


async def test_ask_without_token_returns_401(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = _make_app(app_session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/bot/ask", json={"message": "hi"})
    assert resp.status_code == 401


async def test_ask_with_refresh_token_returns_401(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A refresh token must NOT authorize a resource endpoint (type-split)."""
    app = _make_app(app_session_factory)
    refresh = create_refresh_token(
        tenant_id=uuid.uuid4(), role="player", signing_key=_SIGNING_KEY
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/bot/ask",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {refresh}"},
        )
    assert resp.status_code == 401


async def test_ask_with_denylisted_access_token_returns_401(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = _make_app(app_session_factory)
    token = create_access_token(
        tenant_id=uuid.uuid4(), role="player", signing_key=_SIGNING_KEY
    )
    jti = decode_token(token, _SIGNING_KEY)["jti"]
    await deny(app.state.redis, jti, 60)  # operator force-revoke of this token
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/bot/ask",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 401


async def test_ask_with_garbage_token_returns_401(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = _make_app(app_session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/bot/ask",
            json={"message": "hi"},
            headers={"Authorization": "Bearer not-a-jwt"},
        )
    assert resp.status_code == 401
