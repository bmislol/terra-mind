"""Operator re-rag API + the worker job fn (Phase 5.3, D-033).

Covers the four required behaviours — start→job_id (202), a 2nd start while one
runs→409 (single-job guard), status poll, and player→403 on both — plus the
worker job fn's bookkeeping with `run_build` faked (no real re-rag). The queue
runs on sync fakeredis (enqueue + the NX lock work there; no worker executes the
job), while rerag_jobs rows live in the real Postgres testcontainer.
"""

from __future__ import annotations

import uuid

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.jobs.rerag as rerag_job
from app.api.admin import admin_router
from app.db.models import AuditLog, ReragJob
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets
from app.jobs.queue import RERAG_LOCK_KEY
from app.rag.corpus_build import ProgressFn
from app.repositories.rerag import create_job

_KEY = "test-rerag-signing-key-0123456789"


def _build_app(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[FastAPI, fakeredis.aioredis.FakeRedis]:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(admin_router)
    app.state.session_factory = factory
    app.state.redis = redis  # require_access_token checks the denylist here
    app.state.secrets = AppSecrets(anthropic_api_key="sk-ant-x", jwt_signing_key=_KEY)
    # RQ requires a sync, bytes (decode_responses=False) connection; fakeredis fits.
    app.state.rerag_queue = Queue("rerag", connection=fakeredis.FakeStrictRedis())
    return app, redis


def _header(tenant_id: uuid.UUID, role: str) -> dict[str, str]:
    token = create_access_token(tenant_id=tenant_id, role=role, signing_key=_KEY)
    return {"Authorization": f"Bearer {token}"}


async def test_start_returns_job_id_and_second_is_409(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, redis = _build_app(app_session_factory)
    op = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r1 = await client.post(
            "/admin/rerag", json={"version": "1.4.4.9"}, headers=_header(op, "operator")
        )
        assert r1.status_code == 202
        job_id = r1.json()["job_id"]
        assert r1.json()["status"] == "queued"

        # The enqueued job carries a generous timeout — RQ's 180s default would
        # kill a real (minutes-long) corpus re-rag mid-run (D-033).
        enqueued = app.state.rerag_queue.fetch_job(job_id)
        assert enqueued is not None and enqueued.timeout == 1800

        # A 2nd start while the first holds the lock → 409 (single-job guard).
        r2 = await client.post(
            "/admin/rerag", json={"version": "1.4.4.9"}, headers=_header(op, "operator")
        )
        assert r2.status_code == 409

    # The 409 created no row — exactly one job exists.
    async with app_session_factory() as session:
        rows = (await session.execute(select(ReragJob))).scalars().all()
    assert len(rows) == 1
    assert str(rows[0].id) == job_id
    await redis.aclose()


async def test_status_poll_returns_the_row(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, redis = _build_app(app_session_factory)
    op = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/admin/rerag", json={"version": "1.4.4.9"}, headers=_header(op, "operator")
        )
        job_id = started.json()["job_id"]

        resp = await client.get(
            f"/admin/rerag/status/{job_id}", headers=_header(op, "operator")
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == job_id
        assert body["version"] == "1.4.4.9"
        assert body["status"] == "queued"  # no worker ran it

        # Unknown job → 404.
        missing = await client.get(
            f"/admin/rerag/status/{uuid.uuid4()}", headers=_header(op, "operator")
        )
        assert missing.status_code == 404
    await redis.aclose()


async def test_player_403_on_both_endpoints(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, redis = _build_app(app_session_factory)
    player = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        post = await client.post(
            "/admin/rerag",
            json={"version": "1.4.4.9"},
            headers=_header(player, "player"),
        )
        assert post.status_code == 403
        get = await client.get(
            f"/admin/rerag/status/{uuid.uuid4()}", headers=_header(player, "player")
        )
        assert get.status_code == 403
    await redis.aclose()


async def test_job_fn_succeeds_audits_and_releases_lock(
    app_session_factory: async_sessionmaker[AsyncSession],
    owner_sync_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker job fn (run_build faked): marks the row succeeded, writes the
    corpus.reragged audit, and releases the single-job lock."""
    job_id = uuid.uuid4()
    actor = uuid.uuid4()
    version = "1.4.4.9"
    async with app_session_factory() as session:
        await create_job(session, job_id=job_id, version=version)
        await session.commit()

    fake_redis = fakeredis.FakeStrictRedis()
    fake_redis.set(RERAG_LOCK_KEY, str(job_id))  # the api's lock

    seen: list[tuple[str, bool]] = []

    def fake_run_build(
        v: str, db_url: str, *, force: bool, progress: ProgressFn
    ) -> int:
        assert force is False  # the job never uses --force (D-033)
        progress("loading", 0, 0)
        progress("embedding", 2, 2)
        seen.append((v, force))
        return 0

    monkeypatch.setenv("DATABASE_URL", owner_sync_dsn)
    monkeypatch.setattr(rerag_job, "redis_connection", lambda: fake_redis)
    monkeypatch.setattr(rerag_job, "run_build", fake_run_build)

    result = rerag_job.run_rerag_job(str(job_id), version, str(actor))

    assert result == "succeeded"
    assert seen == [(version, False)]
    assert fake_redis.exists(RERAG_LOCK_KEY) == 0  # lock released

    async with app_session_factory() as session:
        row = await session.get(ReragJob, job_id)
        assert row is not None
        assert row.status == "succeeded"
        assert row.finished_at is not None
        audits = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "corpus.reragged")
                )
            )
            .scalars()
            .all()
        )
    assert any(a.target == version and a.actor == actor for a in audits)
