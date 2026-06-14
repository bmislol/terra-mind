"""fastapi-users integration (Phase 4.1a).

Binds fastapi-users to the **existing** ``tenants`` table (the `Tenant` ORM
model already carries id/email/hashed_password/is_active/is_superuser/
is_verified + guest fields — no migration needed). Password hashing is
**argon2id** (pwdlib) — the modern OWASP-recommended, memory-hard default,
preferred over bcrypt.

Token *issuance* is custom (`app.infra.jwt_tokens`); the fastapi-users auth
backend here exists to construct `FastAPIUsers` (which mounts the register
router) and to supply `current_user` dependencies in later commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.infra.jwt_tokens import ACCESS_TTL_SECONDS

# argon2id only (not bcrypt): memory-hard, GPU-resistant, OWASP default.
_PASSWORD_HELPER = PasswordHelper(PasswordHash((Argon2Hasher(),)))


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield an async session from the app-state session factory (lifespan)."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[Tenant, uuid.UUID]]:
    yield SQLAlchemyUserDatabase(session, Tenant)


class UserManager(UUIDIDMixin, BaseUserManager[Tenant, uuid.UUID]):
    """User manager bound to the tenants table, hashing with argon2id.

    reset/verification token secrets are required by BaseUserManager but the
    reset-password and email-verification flows are intentionally not mounted
    (SECURITY §4); the secret is the Vault signing key, never exercised here.
    """

    def __init__(
        self,
        user_db: SQLAlchemyUserDatabase[Tenant, uuid.UUID],
        *,
        token_secret: str,
    ) -> None:
        super().__init__(user_db, password_helper=_PASSWORD_HELPER)
        self.reset_password_token_secret = token_secret
        self.verification_token_secret = token_secret


async def get_user_manager(
    request: Request,
    user_db: SQLAlchemyUserDatabase[Tenant, uuid.UUID] = Depends(get_user_db),
) -> AsyncGenerator[UserManager]:
    yield UserManager(user_db, token_secret=request.app.state.secrets.jwt_signing_key)


def _get_jwt_strategy(request: Request) -> JWTStrategy[Tenant, uuid.UUID]:
    # Signing key from Vault via app.state (resolved per-request). This backend
    # is used to construct FastAPIUsers / current_user deps; access tokens
    # themselves are issued by app.infra.jwt_tokens with custom claims.
    return JWTStrategy(
        secret=request.app.state.secrets.jwt_signing_key,
        lifetime_seconds=ACCESS_TTL_SECONDS,
    )


_bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")
auth_backend: AuthenticationBackend[Tenant, uuid.UUID] = AuthenticationBackend(
    name="jwt",
    transport=_bearer_transport,
    get_strategy=_get_jwt_strategy,
)

fastapi_users: FastAPIUsers[Tenant, uuid.UUID] = FastAPIUsers(
    get_user_manager,
    [auth_backend],
)


def role_for(user: Tenant) -> str:
    """Map the tenant's is_superuser flag to the JWT role claim."""
    return "operator" if user.is_superuser else "player"


__all__: list[Any] = [
    "UserManager",
    "auth_backend",
    "fastapi_users",
    "get_user_manager",
    "role_for",
]
