"""Shared pytest fixtures.

Postgres-backed auth/RLS tests (Phase 4.1a+) run against a real
``pgvector/pgvector:pg16`` container via testcontainers — RLS
(``current_setting``, FORCE RLS, the ``terramind_app`` **non-superuser** role)
cannot be faked, and a superuser connection would bypass RLS and prove nothing.
The app connects as ``terramind_app``; migrations + cleanup run as the owner.

Requires Docker. Tests that don't request these fixtures never start the
container (session fixtures are lazy).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import fakeredis.aioredis
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from app.api.auth import auth_router
from app.infra.vault import AppSecrets

_BACKEND_DIR = Path(__file__).parent.parent
TEST_SIGNING_KEY = "test-signing-key-not-a-real-secret-0123456789"

_OWNER_USER = "terramind"
_OWNER_PW = "terramind-dev-password"
_APP_USER = "terramind_app"
_APP_PW = "terramind-app-dev-password"
_DB = "terramind"


@dataclass(frozen=True)
class PgInfo:
    owner_sync_dsn: str
    app_async_dsn: str


@pytest.fixture(scope="session")
def _pg() -> Iterator[PgInfo]:
    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        username=_OWNER_USER,
        password=_OWNER_PW,
        dbname=_DB,
    ) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        owner_sync = f"postgresql://{_OWNER_USER}:{_OWNER_PW}@{host}:{port}/{_DB}"

        # The non-superuser app role must exist before migrations GRANT to it.
        with psycopg.connect(owner_sync, autocommit=True) as conn:
            conn.execute(
                f"CREATE ROLE {_APP_USER} LOGIN PASSWORD '{_APP_PW}' NOSUPERUSER"
            )

        # Migrations run as the owner; alembic env.py reads DATABASE_URL.
        os.environ["DATABASE_URL"] = (
            f"postgresql+asyncpg://{_OWNER_USER}:{_OWNER_PW}@{host}:{port}/{_DB}"
        )
        command.upgrade(Config(str(_BACKEND_DIR / "alembic.ini")), "head")

        yield PgInfo(
            owner_sync_dsn=owner_sync,
            app_async_dsn=(
                f"postgresql+asyncpg://{_APP_USER}:{_APP_PW}@{host}:{port}/{_DB}"
            ),
        )


@pytest.fixture
def owner_sync_dsn(_pg: PgInfo) -> str:
    """Owner (superuser) sync DSN — bypasses RLS. For tests that must verify
    physical state (e.g. erasure proving deletion, not RLS masking)."""
    return _pg.owner_sync_dsn


@pytest.fixture
async def app_session_factory(
    _pg: PgInfo,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Per-test async session factory connecting as the non-superuser app role.

    Truncates as the owner first (bypasses RLS; can TRUNCATE) for a clean slate.
    """
    with psycopg.connect(_pg.owner_sync_dsn, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE tenants, sessions, messages, audit_log, rag_chunks,"
            " tenant_preferences, rerag_jobs RESTART IDENTITY CASCADE"
        )
    engine = create_async_engine(_pg.app_async_dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def auth_client(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """A FastAPI app with only the auth router + test app.state (no lifespan).

    Redis is an in-process fakeredis (the denylist needs no real Redis in tests).
    """
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(auth_router)
    app.state.session_factory = app_session_factory
    app.state.redis = redis
    app.state.secrets = AppSecrets(
        anthropic_api_key="sk-ant-not-real",
        jwt_signing_key=TEST_SIGNING_KEY,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await redis.aclose()
