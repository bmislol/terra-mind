"""Endpoint tests for POST /bot/ask.

Uses a minimal fixture app (no lifespan) so these tests never hit Vault,
Langfuse, or the DB.  Service layer is patched at the bot module boundary;
service-layer contracts are covered by tests/services/test_router.py and
tests/services/test_faq.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.bot import bot_router
from app.core.prompts import LoadedPrompts
from app.domain.bot import BotAnswer, ChunkRef, RoutingDecision, StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.pipeline import RetrievalPipeline


def _make_app() -> FastAPI:
    """Minimal FastAPI instance with bot_router and mock state — no lifespan."""
    test_app = FastAPI()
    test_app.include_router(bot_router)
    test_app.state.anthropic = MagicMock(spec=AnthropicClient)
    test_app.state.retrieval_pipeline = MagicMock(spec=RetrievalPipeline)
    test_app.state.prompts = LoadedPrompts(
        router="You are a router.",
        faq_answer="You are a FAQ assistant.",
        agent_system="You are an agent.",
    )
    return test_app


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
    answer=(
        "I'd need to think about your situation more carefully than I can right now. "
        "Try asking about specific items, recipes, or game mechanics instead."
    ),
    source_chunks=[],
    routing=RoutingDecision.agent,
)


async def test_ask_faq_question_returns_200_with_routing_faq() -> None:
    app = _make_app()
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
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["routing"] == "faq"
    assert data["answer"] == "The Megashark deals 25 base damage."
    assert len(data["source_chunks"]) == 1
    assert data["source_chunks"][0]["page_title"] == "Megashark"


async def test_ask_agent_question_returns_200_with_routing_agent() -> None:
    app = _make_app()
    with (
        patch(
            "app.api.bot.router_svc.classify",
            AsyncMock(return_value=RoutingDecision.agent),
        ),
        patch(
            "app.api.bot.agent_svc.answer",
            AsyncMock(return_value=_AGENT_ANSWER),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/bot/ask",
                json={"message": "Why do I keep dying to Skeletron?"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["routing"] == "agent"
    assert data["source_chunks"] == []


async def test_ask_default_state_uses_default_game_version() -> None:
    """body.state=None → faq.answer receives StatePayload(game_version='1.4.4.9')."""
    mock_faq = AsyncMock(return_value=_FAQ_ANSWER)
    app = _make_app()
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
            resp = await client.post("/bot/ask", json={"message": "What damage?"})

    assert resp.status_code == 200
    # Second positional arg is the StatePayload
    state_arg: StatePayload = mock_faq.call_args.args[1]
    assert state_arg.game_version == "1.4.4.9"


async def test_ask_missing_message_returns_422() -> None:
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/bot/ask", json={})

    assert resp.status_code == 422
