"""The operator re-rag background job (Phase 5.3, D-033).

Runs in the RQ **worker** process (sync). It calls ``run_build`` with
``force=False`` — the idempotent, retry-safe upsert path — and threads a progress
callback that writes BOTH the Redis live-progress hash and the durable
``rerag_jobs`` row, so the status endpoint (in the api process) sees fresh
progress across the two-process boundary.

On success it writes the ``corpus.reragged`` audit row (ARCH §6, surfaced in the
5.2 operator audit view) and marks the job succeeded. On failure it records the
error and **re-raises**, so RQ marks the job failed and retries (safe — the
upsert is idempotent). Either way it releases the single-job lock; the lock's TTL
is the safety net if the worker dies mid-job.

The worker has ``DATABASE_URL`` + the data volume + the embedding model (compose,
commit 1) and **no Vault** — ``run_build`` needs none. DB writes use a short-lived
SYNC engine + ORM session (the worker is sync; the build already writes sync).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AuditLog, ReragJob
from app.jobs.queue import (
    RERAG_LOCK_KEY,
    RERAG_LOCK_TTL_SECONDS,
    RERAG_PROGRESS_TTL_SECONDS,
    redis_connection,
    rerag_progress_key,
)
from app.rag.corpus_build import run_build, sync_db_url


def run_rerag_job(job_id: str, version: str, requested_by: str) -> str:
    """RQ entrypoint. Returns ``"succeeded"``; raises (after recording it) on
    failure so RQ marks the job failed and retries."""
    db_url = os.environ["DATABASE_URL"]
    redis = redis_connection()  # sync, from RQ_REDIS_URL (the worker's env)
    engine = create_engine(sync_db_url(db_url))
    jid = UUID(job_id)
    progress_key = rerag_progress_key(job_id)

    def progress(stage: str, done: int, total: int) -> None:
        # Live progress to Redis (frequent, cheap) ...
        redis.hset(progress_key, mapping={"stage": stage, "done": done, "total": total})
        redis.expire(progress_key, RERAG_PROGRESS_TTL_SECONDS)
        # ... heartbeat the lock so a live job never self-expires ...
        redis.expire(RERAG_LOCK_KEY, RERAG_LOCK_TTL_SECONDS)
        # ... and the durable row the status endpoint reads.
        with Session(engine) as session:
            row = session.get(ReragJob, jid)
            if row is not None:
                row.stage, row.done, row.total = stage, done, total
                session.commit()

    try:
        # Mark running.
        with Session(engine) as session:
            job = session.get(ReragJob, jid)
            if job is not None:
                job.status = "running"
                job.started_at = datetime.now(UTC)
                session.commit()

        try:
            rc = run_build(version, db_url, force=False, progress=progress)
            if rc != 0:
                raise RuntimeError(
                    f"build_corpus exited {rc} (corpus missing or invalid on disk)"
                )
        except Exception as exc:
            with Session(engine) as session:
                row = session.get(ReragJob, jid)
                if row is not None:
                    row.status = "failed"
                    row.error = str(exc)[:1000]
                    row.finished_at = datetime.now(UTC)
                    session.commit()
            redis.delete(RERAG_LOCK_KEY)
            raise

        # Success: corpus.reragged audit + mark succeeded + release lock + clear hash.
        with Session(engine) as session:
            session.add(
                AuditLog(
                    actor=UUID(requested_by),
                    action="corpus.reragged",
                    target=version,
                    meta={"job_id": job_id},
                )
            )
            row = session.get(ReragJob, jid)
            if row is not None:
                row.status = "succeeded"
                row.finished_at = datetime.now(UTC)
            session.commit()
        redis.delete(RERAG_LOCK_KEY)
        redis.delete(progress_key)
        return "succeeded"
    finally:
        engine.dispose()
