"""Session-revocation denylist (D-029), backed by Redis.

A token's ``jti`` is added on logout / operator force-revoke with a TTL equal
to the token's remaining lifetime, so the entry self-expires exactly when the
token would have expired anyway — no unbounded growth, no GC job. ``/auth/refresh``
and the authed request path check ``is_denied`` before honoring a token.

The Redis client is injected (passed as a parameter), never imported as a
global (ARCH §8.1). Reuses the stack's existing Redis (D-010) — no new service.
"""

from __future__ import annotations

from redis.asyncio import Redis

_PREFIX = "denylist:jti:"


async def deny(redis: Redis, jti: str, ttl_seconds: int) -> None:
    """Denylist *jti* for *ttl_seconds* (self-expiring). TTL is floored at 1s."""
    await redis.set(f"{_PREFIX}{jti}", "1", ex=max(ttl_seconds, 1))


async def is_denied(redis: Redis, jti: str) -> bool:
    """True if *jti* is currently denylisted."""
    return bool(await redis.exists(f"{_PREFIX}{jti}"))
