"""Operator re-rag orchestration (Phase 5.3, D-033).

Starts the background re-rag job and reports its status. Like the other operator
services (admin), it sets **no tenant context** — `rerag_jobs` is operator/cross-
tenant data with no RLS (D-017); the authorization boundary is `require_operator`
at the route. The single-job guard is a Redis lock acquired here (SET NX) and
released by the worker on finish (app/jobs/rerag.py).

RQ is sync, so the queue/lock calls here are sync calls from the async handler —
tiny, local-Redis operations on a low-traffic operator endpoint.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from rq import Queue, Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin import ReragStartResponse, ReragStatus
from app.jobs.queue import (
    RERAG_LOCK_KEY,
    RERAG_LOCK_TTL_SECONDS,
    rerag_progress_key,
)
from app.jobs.rerag import run_rerag_job
from app.repositories import rerag as rerag_repo


class ReragInProgress(Exception):
    """A re-rag is already running — the single-job guard rejected a 2nd start."""


def _decode(raw: dict[Any, Any]) -> dict[str, str]:
    """The RQ Redis connection is bytes (decode_responses=False); decode here."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = key.decode() if isinstance(key, bytes) else str(key)
        v = value.decode() if isinstance(value, bytes) else str(value)
        out[k] = v
    return out


async def start_rerag(
    session_factory: async_sessionmaker[AsyncSession],
    queue: Queue,
    *,
    version: str,
    requested_by: UUID,
) -> ReragStartResponse:
    """Acquire the single-job lock (raise ReragInProgress if held), record the
    job row, and enqueue it onto the worker."""
    job_id = uuid4()
    conn = queue.connection
    # SET NX EX — the single-job guard. The worker releases it on finish; the TTL
    # frees it if the worker dies (D-033).
    acquired = conn.set(RERAG_LOCK_KEY, str(job_id), nx=True, ex=RERAG_LOCK_TTL_SECONDS)
    if not acquired:
        raise ReragInProgress
    try:
        async with session_factory() as session:
            await rerag_repo.create_job(session, job_id=job_id, version=version)
            await session.commit()
        queue.enqueue(
            run_rerag_job,
            str(job_id),
            version,
            str(requested_by),
            job_id=str(job_id),
            retry=Retry(max=2),
        )
    except Exception:
        # Roll the lock back so a transient failure doesn't wedge re-rag.
        conn.delete(RERAG_LOCK_KEY)
        raise
    return ReragStartResponse(job_id=job_id, status="queued")


async def get_rerag_status(
    session_factory: async_sessionmaker[AsyncSession],
    queue: Queue,
    job_id: UUID,
) -> ReragStatus | None:
    """The durable rerag_jobs row, with the freshest live progress overlaid from
    Redis (the worker writes both; the row outlives the hash's TTL)."""
    async with session_factory() as session:
        job = await rerag_repo.get_job(session, job_id)
    if job is None:
        return None

    stage, done, total = job.stage, job.done, job.total
    live = _decode(queue.connection.hgetall(rerag_progress_key(str(job_id))))
    if live:
        stage = live.get("stage") or stage
        done = int(live.get("done", done))
        total = int(live.get("total", total))

    return ReragStatus(
        job_id=job.id,
        version=job.version,
        status=job.status,
        stage=stage,
        done=done,
        total=total,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
