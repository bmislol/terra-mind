"""Auth HTTP surface (Phase 4.1a).

POST /auth/register — fastapi-users register router (privilege-safe: it strips
  is_superuser/is_active/is_verified, so a player cannot self-register as
  operator; the first operator comes from the bootstrap script, RUNBOOK §3).
POST /auth/jwt/login — custom login: authenticate via the user manager, then
  issue a custom access JWT (tenant_id + role + jti + type, app.infra.jwt_tokens).

Refresh token + /auth/refresh + logout land in commit 2; guest + operator-403
in commit 4.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import schemas
from pydantic import BaseModel

from app.infra.auth import UserManager, fastapi_users, get_user_manager, role_for
from app.infra.jwt_tokens import create_access_token, create_refresh_token
from app.services import auth as auth_svc


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


auth_router = APIRouter(prefix="/auth", tags=["auth"])

# POST /auth/register (privilege-safe create via the user manager).
auth_router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))


@auth_router.post("/jwt/login", response_model=TokenPairResponse)
async def login(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    user_manager: UserManager = Depends(get_user_manager),
) -> TokenPairResponse:
    """Validate username/password and return an access + refresh token pair."""
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS",
        )
    key = request.app.state.secrets.jwt_signing_key
    role = role_for(user)
    await auth_svc.record_login(
        user.id, session_factory=request.app.state.session_factory
    )
    return TokenPairResponse(
        access_token=create_access_token(tenant_id=user.id, role=role, signing_key=key),
        refresh_token=create_refresh_token(
            tenant_id=user.id, role=role, signing_key=key
        ),
    )


@auth_router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(request: Request, body: RefreshRequest) -> AccessTokenResponse:
    """Exchange a valid (non-denylisted) refresh token for a new access token.

    This is the endpoint the mod's saved-token exchange uses (D-027 folded
    /client/token into /auth/refresh).
    """
    try:
        access = await auth_svc.refresh_access_token(
            body.refresh_token,
            redis=request.app.state.redis,
            signing_key=request.app.state.secrets.jwt_signing_key,
        )
    except auth_svc.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_REFRESH_TOKEN"
        ) from exc
    return AccessTokenResponse(access_token=access)


@auth_router.post("/guest", response_model=AccessTokenResponse)
async def guest(request: Request) -> AccessTokenResponse:
    """Create an ephemeral guest tenant and return an access-only token (D-027)."""
    token = await auth_svc.create_guest_session(
        session_factory=request.app.state.session_factory,
        signing_key=request.app.state.secrets.jwt_signing_key,
    )
    return AccessTokenResponse(access_token=token)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, body: RefreshRequest) -> None:
    """Revoke a session: denylist the refresh token's jti + audit it (D-029)."""
    try:
        await auth_svc.logout(
            body.refresh_token,
            redis=request.app.state.redis,
            signing_key=request.app.state.secrets.jwt_signing_key,
            session_factory=request.app.state.session_factory,
        )
    except auth_svc.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_REFRESH_TOKEN"
        ) from exc
