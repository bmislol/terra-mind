"""Shared API dependencies (Phase 4.1a).

`require_access_token` is the resource-endpoint auth gate: api/ extracts the
Bearer token and delegates validation to the auth service (ARCH §4 — the
service owns token logic + the denylist check). A missing/invalid/refresh/
revoked token yields 401 before the handler runs.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth import AccessContext, AuthError, authenticate_access

_bearer = HTTPBearer(auto_error=False)


async def require_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AccessContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MISSING_BEARER_TOKEN",
        )
    try:
        return await authenticate_access(
            credentials.credentials,
            redis=request.app.state.redis,
            signing_key=request.app.state.secrets.jwt_signing_key,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_ACCESS_TOKEN",
        ) from exc


async def require_operator(
    auth: AccessContext = Depends(require_access_token),
) -> AccessContext:
    """Operator-only gate (SECURITY §5). A player-role token gets 403 before
    the handler runs; the access token is already validated by the dependency."""
    if auth.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OPERATOR_REQUIRED",
        )
    return auth
