"""GET /versions — distinct corpus game versions (Phase 5.1)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.versions import versions_router
from app.db.models import RagChunk


def _app(factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    app.include_router(versions_router)
    app.state.session_factory = factory
    return app


async def _seed_chunk(
    factory: async_sessionmaker[AsyncSession], *, game_version: str, page_id: int
) -> None:
    async with factory() as session:
        session.add(
            RagChunk(
                id=uuid.uuid4(),
                page_id=page_id,
                chunk_index=0,
                game_version=game_version,
                page_title="Test",
                content="body",
                embedding=[0.0] * 384,
            )
        )
        await session.commit()


async def test_versions_returns_distinct_sorted(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Two chunks share a version (distinct page_id avoids the unique key);
    # the response must collapse them and sort ascending.
    await _seed_chunk(app_session_factory, game_version="1.4.4.9", page_id=1)
    await _seed_chunk(app_session_factory, game_version="1.4.4.9", page_id=2)
    await _seed_chunk(app_session_factory, game_version="1.3.5.3", page_id=3)

    async with AsyncClient(
        transport=ASGITransport(app=_app(app_session_factory)),
        base_url="http://test",
    ) as client:
        resp = await client.get("/versions")

    assert resp.status_code == 200
    assert resp.json() == {"versions": ["1.3.5.3", "1.4.4.9"]}


async def test_versions_empty_corpus(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(app_session_factory)),
        base_url="http://test",
    ) as client:
        resp = await client.get("/versions")
    assert resp.status_code == 200
    assert resp.json() == {"versions": []}
