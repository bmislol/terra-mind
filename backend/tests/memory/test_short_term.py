"""Unit tests for app/memory/short_term.py — in-process fakeredis, no real Redis.

Covers append/get ordering, the sliding window (LTRIM to N), TTL (EXPIRE),
clear, per-(tenant, session) key isolation, and — mirroring the redaction-test
discipline (SECURITY §7.2) — that a planted secret never lands in Redis
unredacted.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest

from app.memory.short_term import (
    HISTORY_TTL_SECONDS,
    HISTORY_WINDOW,
    _key,
    append_message,
    clear,
    get_history,
)

_TENANT = uuid.uuid4()
_SESSION = uuid.uuid4()


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def test_append_and_get_history_preserves_order(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await append_message(
        redis, tenant_id=_TENANT, session_id=_SESSION, role="user", content="hi"
    )
    await append_message(
        redis, tenant_id=_TENANT, session_id=_SESSION, role="assistant", content="hey"
    )
    history = await get_history(redis, tenant_id=_TENANT, session_id=_SESSION)
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]


async def test_window_trims_to_last_n(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    for i in range(HISTORY_WINDOW + 5):
        await append_message(
            redis, tenant_id=_TENANT, session_id=_SESSION, role="user", content=str(i)
        )
    history = await get_history(redis, tenant_id=_TENANT, session_id=_SESSION)
    assert len(history) == HISTORY_WINDOW
    # Oldest 5 dropped; the window holds the most recent N.
    assert history[0]["content"] == "5"
    assert history[-1]["content"] == str(HISTORY_WINDOW + 4)


async def test_append_sets_sliding_ttl(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await append_message(
        redis, tenant_id=_TENANT, session_id=_SESSION, role="user", content="hi"
    )
    ttl = await redis.ttl(_key(_TENANT, _SESSION))
    assert 0 < ttl <= HISTORY_TTL_SECONDS


async def test_clear_removes_history(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await append_message(
        redis, tenant_id=_TENANT, session_id=_SESSION, role="user", content="hi"
    )
    await clear(redis, tenant_id=_TENANT, session_id=_SESSION)
    assert await get_history(redis, tenant_id=_TENANT, session_id=_SESSION) == []


async def test_history_is_isolated_per_tenant_and_session(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    other_tenant = uuid.uuid4()
    await append_message(
        redis, tenant_id=_TENANT, session_id=_SESSION, role="user", content="mine"
    )
    # Different tenant, same session_id → different key → no leakage.
    assert await get_history(redis, tenant_id=other_tenant, session_id=_SESSION) == []
    # Different session under the same tenant → also isolated.
    assert await get_history(redis, tenant_id=_TENANT, session_id=uuid.uuid4()) == []


async def test_content_is_redacted_before_redis_write(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A planted Anthropic key must never land in Redis unredacted (SECURITY §7.2)."""
    secret = "sk-ant-api03-FAKE-not-real-do-not-store"
    await append_message(
        redis,
        tenant_id=_TENANT,
        session_id=_SESSION,
        role="user",
        content=f"my key is {secret} ok?",
    )
    # Read the raw stored element straight from Redis (bypassing get_history).
    raw = await redis.lrange(_key(_TENANT, _SESSION), 0, -1)
    assert secret not in raw[0]
    assert "sk-ant" not in raw[0]
    assert "[REDACTED]" in json.loads(raw[0])["content"]
