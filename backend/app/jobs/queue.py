"""RQ queue wiring for the operator re-rag job (Phase 5.3, D-033).

RQ uses a **synchronous** Redis connection — distinct from the app's
``redis.asyncio`` client (denylist/short-term memory) — so this module owns its
own sync connection from the same Redis. Both the api (which *enqueues*) and the
dockerised ``rq worker rerag`` (which *runs* jobs) point at one Redis:

- the worker reads ``RQ_REDIS_URL`` (set in compose) — the same env the
  ``rq`` CLI consumes for ``--url``;
- the api passes ``settings.redis_url`` explicitly (commit 3).

Both default to ``redis://redis:6379/0``, the one Redis the stack runs.
"""

from __future__ import annotations

import os

from redis import Redis
from rq import Queue

#: The single queue re-rag jobs are enqueued onto / the worker listens on.
RERAG_QUEUE = "rerag"

#: Single-job guard: a 2nd /admin/rerag while one runs is rejected (409). The api
#: acquires it (SET NX) at enqueue; the worker releases it on finish and refreshes
#: its TTL each progress tick, so a live job never self-expires but a *dead*
#: worker's lock frees within the TTL (D-033).
RERAG_LOCK_KEY = "rerag:lock"
#: Lock TTL — comfortably longer than a real CPU re-rag of this corpus; refreshed
#: on every progress tick (heartbeat).
RERAG_LOCK_TTL_SECONDS = 1800
#: Live-progress hash TTL — the hash self-cleans; the durable rerag_jobs row is
#: the source of truth once it's gone.
RERAG_PROGRESS_TTL_SECONDS = 3600

_DEFAULT_REDIS_URL = "redis://redis:6379/0"


def rerag_progress_key(job_id: str) -> str:
    """Redis hash key for a job's live ``{stage, done, total}`` progress."""
    return f"rerag:progress:{job_id}"


def redis_connection(url: str | None = None) -> Redis:
    """A sync Redis connection for RQ.

    Falls back to ``RQ_REDIS_URL`` (the worker's env) then the stack default,
    so the worker and the api resolve to the same Redis without a hardcoded URL.
    """
    return Redis.from_url(url or os.environ.get("RQ_REDIS_URL", _DEFAULT_REDIS_URL))


def rerag_queue(connection: Redis | None = None) -> Queue:
    """The ``rerag`` queue, bound to the given (or a default) connection."""
    return Queue(RERAG_QUEUE, connection=connection or redis_connection())
