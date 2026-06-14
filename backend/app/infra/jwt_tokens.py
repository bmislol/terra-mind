"""Custom JWT issuance/verification (Phase 4.1a, D-027/D-029).

fastapi-users' built-in JWTStrategy is access-only and carries only ``sub``;
the auth shape needs custom claims — ``tenant_id`` (RLS-context source),
``role``, ``jti`` (denylist key, D-029), and ``type`` (access vs refresh) — so
tokens are issued/verified here with pyjwt directly. The HS256 signing key
comes from Vault (``app.state.secrets.jwt_signing_key``), never a module
constant or env var.

Commit 1 builds the access token only; the refresh token + denylist land in
commit 2. TTLs are server-pinned (D-006, graduated in Phase 4.1a): access
30 min, refresh 30 days.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any
from uuid import UUID

import jwt

ALGORITHM = "HS256"
# Server-pinned TTLs (D-006, graduated in Phase 4.1a). 30-min access bounds
# leak damage; 30-day refresh = "stay logged in a month" (revocable via D-029).
ACCESS_TTL_SECONDS = 30 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60


def _create_token(
    *,
    tenant_id: UUID,
    role: str,
    token_type: str,
    ttl_seconds: int,
    signing_key: str,
    now: datetime.datetime | None = None,
) -> str:
    issued = now or datetime.datetime.now(tz=datetime.UTC)
    expires = issued + datetime.timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(tenant_id),
        "role": role,
        "jti": uuid.uuid4().hex,
        "type": token_type,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, signing_key, algorithm=ALGORITHM)


def create_access_token(
    *,
    tenant_id: UUID,
    role: str,
    signing_key: str,
    now: datetime.datetime | None = None,
) -> str:
    """Mint a signed access JWT (``type=access``, 30-min TTL).

    ``sub`` is the tenant_id (the RLS-context source); ``role`` is ``"player"``
    or ``"operator"``; ``jti`` is unique (denylist key, D-029). Only this token
    type authorizes resource endpoints.
    """
    return _create_token(
        tenant_id=tenant_id,
        role=role,
        token_type="access",
        ttl_seconds=ACCESS_TTL_SECONDS,
        signing_key=signing_key,
        now=now,
    )


def create_refresh_token(
    *,
    tenant_id: UUID,
    role: str,
    signing_key: str,
    now: datetime.datetime | None = None,
) -> str:
    """Mint a signed refresh JWT (``type=refresh``, 30-day TTL).

    Does one thing: mint a new access token at ``/auth/refresh``. It cannot
    authorize a resource endpoint (the resource dependency requires
    ``type=access``). Revocable by denylisting its ``jti`` (logout, D-029).
    """
    return _create_token(
        tenant_id=tenant_id,
        role=role,
        token_type="refresh",
        ttl_seconds=REFRESH_TTL_SECONDS,
        signing_key=signing_key,
        now=now,
    )


def decode_token(token: str, signing_key: str) -> dict[str, Any]:
    """Decode + verify a token's signature and expiry. Raises on failure.

    Raises ``jwt.InvalidTokenError`` (incl. ``ExpiredSignatureError`` and
    ``InvalidSignatureError``) on any verification failure. Claim-level checks
    (``type``, denylist) are the caller's responsibility.
    """
    claims: dict[str, Any] = jwt.decode(token, signing_key, algorithms=[ALGORITHM])
    return claims


def remaining_ttl_seconds(
    claims: dict[str, Any], *, now: datetime.datetime | None = None
) -> int:
    """Seconds until ``exp`` (>= 0), for sizing the denylist entry's TTL."""
    current = now or datetime.datetime.now(tz=datetime.UTC)
    return max(0, int(claims["exp"]) - int(current.timestamp()))
