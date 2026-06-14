"""Auth orchestration: refresh-token exchange and logout/revocation (D-029).

Layer boundary (ARCH §4): the API calls these; they combine token verification
(infra), the Redis denylist (memory), and the audit write (repositories). On any
invalid/revoked token they raise ``AuthError``, which the API maps to 401.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.jwt_tokens import (
    create_access_token,
    decode_token,
    remaining_ttl_seconds,
)
from app.memory.denylist import deny, is_denied
from app.repositories.audit import write_audit
from app.repositories.tenants import create_guest

# Guest tenant lifetime marker (cleanup is a later phase). The guest's *access*
# token is still the standard 30 min; access-only, no refresh (ephemeral).
GUEST_TTL_SECONDS = 24 * 60 * 60


class AuthError(Exception):
    """Token invalid, wrong type, or revoked. The API maps this to HTTP 401."""


@dataclass(frozen=True)
class AccessContext:
    """The authenticated principal of a request (from a valid access token)."""

    tenant_id: UUID
    role: str
    jti: str


async def authenticate_access(
    token: str,
    *,
    redis: Redis,
    signing_key: str,
) -> AccessContext:
    """Validate a Bearer **access** token → the request's AccessContext.

    Rejects (AuthError → 401): bad signature/expiry, a non-access token (a
    refresh token must NOT authorize a resource endpoint), or a denylisted jti
    (operator force-revoke; D-029).
    """
    try:
        claims = decode_token(token, signing_key)
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid access token") from exc
    if claims.get("type") != "access":
        raise AuthError("not an access token")
    jti = str(claims["jti"])
    if await is_denied(redis, jti):
        raise AuthError("access token revoked")
    return AccessContext(
        tenant_id=UUID(str(claims["sub"])),
        role=str(claims["role"]),
        jti=jti,
    )


def _verify_refresh_claims(refresh_token: str, signing_key: str) -> dict[str, object]:
    try:
        claims = decode_token(refresh_token, signing_key)
    except jwt.InvalidTokenError as exc:  # bad signature, expired, malformed
        raise AuthError("invalid refresh token") from exc
    if claims.get("type") != "refresh":
        raise AuthError("not a refresh token")
    return claims


async def refresh_access_token(
    refresh_token: str,
    *,
    redis: Redis,
    signing_key: str,
) -> str:
    """Validate a refresh token (type/expiry/denylist) → mint a new access token.

    No rotation (P-014): the same refresh token keeps working until it expires
    or is denylisted at logout. Role/tenant are taken from the refresh claims.
    """
    claims = _verify_refresh_claims(refresh_token, signing_key)
    if await is_denied(redis, str(claims["jti"])):
        raise AuthError("refresh token revoked")
    return create_access_token(
        tenant_id=UUID(str(claims["sub"])),
        role=str(claims["role"]),
        signing_key=signing_key,
    )


async def record_login(
    tenant_id: UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Write an ``auth.login`` audit row (SECURITY §6). Called on successful
    login; refresh is intentionally NOT audited (every-30-min noise)."""
    async with session_factory() as session:
        await write_audit(session, actor=tenant_id, action="auth.login")
        await session.commit()


async def create_guest_session(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    signing_key: str,
) -> str:
    """Create an ephemeral guest tenant and return an **access-only** token.

    Guests get no refresh token (ephemeral); when the 30-min access token
    expires they re-guest. Their data IS erasable on DELETE /me (erasure §4).
    """
    async with session_factory() as session:
        guest = await create_guest(session, ttl_seconds=GUEST_TTL_SECONDS)
        guest_id = guest.id  # set in Python; available before commit
        await write_audit(session, actor=guest_id, action="auth.login", target="guest")
        await session.commit()
    return create_access_token(
        tenant_id=guest_id, role="player", signing_key=signing_key
    )


async def logout(
    refresh_token: str,
    *,
    redis: Redis,
    signing_key: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Denylist the refresh token's jti (TTL = remaining life) + audit it.

    The current access token is not denylisted — it dies within its 30-min TTL
    on its own; denylisting the refresh jti stops it minting new ones.
    """
    claims = _verify_refresh_claims(refresh_token, signing_key)
    jti = str(claims["jti"])
    await deny(redis, jti, remaining_ttl_seconds(claims))
    async with session_factory() as session:
        await write_audit(
            session,
            actor=UUID(str(claims["sub"])),
            action="session.revoked",
            target=jti,
        )
        await session.commit()
