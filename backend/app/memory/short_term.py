"""Short-term session memory over Redis (ARCH §8, D-010 — short-term only).

Per-session message history as a Redis list under
``session:{tenant_id}:{session_id}:messages``; each element is a JSON
``{"role", "content"}``. Sliding window via ``RPUSH`` + ``LTRIM`` to the last
``HISTORY_WINDOW`` messages; a sliding ``EXPIRE`` (reset on each append) gives a
self-expiring TTL so idle sessions clean themselves up — no GC job, no
long-term memory (D-010).

The Redis client is injected (passed as a parameter), never a global import
(ARCH §8.1 — same pattern as the D-029 denylist). **Content is redacted before
it is written** (SECURITY §7.1), so no secret can land in Redis unredacted.

Window/TTL are P-004 **defended estimates** (reasoned defaults, not measured —
no session telemetry exists yet; graduate to D-031 in deliverables) and are
parameters so a caller can override them from config / tune against real
telemetry later.

**Status note:** as of Phase 4.1b the *write* path is live on ``/bot/ask`` (it
is the per-tenant data the RLS isolation proof operates on); the *read* path
(``get_history``) is built and tested but **intentionally not yet consumed** by
the request path — it wires to a consumer (agent conversational memory / a
history endpoint) in a later phase. Written-but-not-yet-read is by design, not
a bug.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.infra.redaction import redact

# P-004 defended estimates (→ D-031). N ≈ 10 user+assistant turns; 2 h ≈ a play
# session with breaks. Config-overridable via the function parameters.
HISTORY_WINDOW = 20
HISTORY_TTL_SECONDS = 2 * 60 * 60


def _key(tenant_id: UUID, session_id: UUID) -> str:
    return f"session:{tenant_id}:{session_id}:messages"


async def append_message(
    redis: Redis,
    *,
    tenant_id: UUID,
    session_id: UUID,
    role: str,
    content: str,
    window: int = HISTORY_WINDOW,
    ttl_seconds: int = HISTORY_TTL_SECONDS,
) -> None:
    """Append one turn (redacted) and keep only the last *window* messages.

    ``redact`` runs on *content* before the write — no secret reaches Redis.
    ``EXPIRE`` is reset on every append (sliding TTL): active sessions stay
    alive, idle ones self-expire after *ttl_seconds*.
    """
    key = _key(tenant_id, session_id)
    element = json.dumps({"role": role, "content": redact(content)})
    await redis.rpush(key, element)
    await redis.ltrim(key, -window, -1)
    await redis.expire(key, ttl_seconds)


async def get_history(
    redis: Redis,
    *,
    tenant_id: UUID,
    session_id: UUID,
) -> list[dict[str, str]]:
    """Return the session's messages oldest→newest as ``{role, content}`` dicts."""
    raw: list[Any] = await redis.lrange(_key(tenant_id, session_id), 0, -1)
    return [json.loads(item) for item in raw]


async def clear(redis: Redis, *, tenant_id: UUID, session_id: UUID) -> None:
    """Delete a session's history (used by right-to-erasure, Phase 4.1b)."""
    await redis.delete(_key(tenant_id, session_id))
