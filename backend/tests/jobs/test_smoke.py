"""Round-trip test for the RQ worker/broker infra (Phase 5.3, commit 1).

Uses a **real Redis** (testcontainers) + a real ``SimpleWorker`` — consistent
with the real-Postgres RLS tests (no mock proves the worker actually runs).
fakeredis can't stand in for the round-trip: rq's worker registration reads
``CLIENT LIST``, which fakeredis returns without the ``addr`` field rq needs.

``SimpleWorker`` runs the job in-process (no ``os.fork``, unlike the default
``Worker``) in **burst** mode — drain the queued jobs, then exit — the same
enqueue → worker → result path the dockerised ``rq worker rerag`` runs.

Requires Docker (like the Postgres fixtures).
"""

from __future__ import annotations

from collections.abc import Iterator

import fakeredis
import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from testcontainers.redis import RedisContainer

from app.jobs.queue import RERAG_QUEUE, rerag_queue
from app.jobs.smoke import ping


@pytest.fixture
def redis_conn() -> Iterator[Redis]:
    """A real Redis (matching the stack's `redis:7-alpine`) for the round-trip."""
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(6379))
        conn: Redis = Redis(host=host, port=port)
        try:
            yield conn
        finally:
            conn.close()


def test_smoke_job_round_trip(redis_conn: Redis) -> None:
    queue = Queue(RERAG_QUEUE, connection=redis_conn)

    job = queue.enqueue(ping)
    assert job.is_queued

    worker = SimpleWorker([queue], connection=redis_conn)
    worker.work(burst=True)

    job.refresh()
    assert job.is_finished
    assert job.return_value() == "pong"


def test_rerag_queue_uses_the_rerag_name() -> None:
    # The api enqueues onto the same name the worker (`rq worker rerag`) drains;
    # a rename would silently desync the two. fakeredis suffices (no worker here).
    queue = rerag_queue(connection=fakeredis.FakeStrictRedis())
    assert queue.name == RERAG_QUEUE == "rerag"
