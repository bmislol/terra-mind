"""Phase 4.1a auth endpoint tests — real Postgres via testcontainers (Docker).

Covers register (incl. privilege-safe create), custom login + access-token
claims, bad-credential 400s, and that the Vault signing key actually signs the
token (decode fails under a different key).
"""

from __future__ import annotations

import datetime
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Tenant
from app.infra.jwt_tokens import (
    ACCESS_TTL_SECONDS,
    REFRESH_TTL_SECONDS,
    create_refresh_token,
    decode_token,
)
from tests.conftest import TEST_SIGNING_KEY

_EMAIL = "player@example.com"
_PASSWORD = "s3cret-pw"


def _register_body(email: str = _EMAIL, password: str = _PASSWORD) -> dict[str, str]:
    return {"email": email, "password": password}


def _login_form(email: str = _EMAIL, password: str = _PASSWORD) -> dict[str, str]:
    return {"username": email, "password": password}


async def test_register_creates_player_tenant(auth_client: AsyncClient) -> None:
    resp = await auth_client.post("/auth/register", json=_register_body())
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == _EMAIL
    assert data["is_superuser"] is False
    assert "id" in data


async def test_register_cannot_self_elevate_to_operator(
    auth_client: AsyncClient,
) -> None:
    """safe create strips is_superuser — register can't grant operator."""
    resp = await auth_client.post(
        "/auth/register",
        json={
            "email": "sneaky@example.com",
            "password": "pw123456",
            "is_superuser": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["is_superuser"] is False


async def test_login_returns_access_token_with_claims(auth_client: AsyncClient) -> None:
    reg = await auth_client.post("/auth/register", json=_register_body())
    tenant_id = reg.json()["id"]

    resp = await auth_client.post("/auth/jwt/login", data=_login_form())
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"

    claims = decode_token(body["access_token"], TEST_SIGNING_KEY)
    assert claims["sub"] == tenant_id
    assert claims["role"] == "player"
    assert claims["type"] == "access"
    assert "jti" in claims
    assert claims["exp"] - claims["iat"] == ACCESS_TTL_SECONDS  # 30 min, server-set


async def test_login_bad_password_returns_400(auth_client: AsyncClient) -> None:
    await auth_client.post("/auth/register", json=_register_body())
    resp = await auth_client.post(
        "/auth/jwt/login", data=_login_form(password="wrong-pw")
    )
    assert resp.status_code == 400


async def test_login_unknown_user_returns_400(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        "/auth/jwt/login", data=_login_form(email="nobody@example.com")
    )
    assert resp.status_code == 400


async def test_signing_key_actually_consumed(auth_client: AsyncClient) -> None:
    """The token verifies under the Vault key and fails under a different key."""
    await auth_client.post("/auth/register", json=_register_body())
    resp = await auth_client.post("/auth/jwt/login", data=_login_form())
    token = resp.json()["access_token"]

    decode_token(token, TEST_SIGNING_KEY)  # correct key: no raise
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, "a-completely-different-signing-key")


# ── Refresh + logout + denylist (commit 2) ────────────────────────────────────


async def _login_tokens(client: AsyncClient) -> tuple[str, str]:
    """Register + login, returning (access_token, refresh_token)."""
    await client.post("/auth/register", json=_register_body())
    resp = await client.post("/auth/jwt/login", data=_login_form())
    body = resp.json()
    return body["access_token"], body["refresh_token"]


async def test_login_returns_token_pair(auth_client: AsyncClient) -> None:
    access, refresh = await _login_tokens(auth_client)
    access_claims = decode_token(access, TEST_SIGNING_KEY)
    refresh_claims = decode_token(refresh, TEST_SIGNING_KEY)
    assert access_claims["type"] == "access"
    assert refresh_claims["type"] == "refresh"
    assert refresh_claims["exp"] - refresh_claims["iat"] == REFRESH_TTL_SECONDS
    # Distinct jtis so the refresh can be revoked independently.
    assert access_claims["jti"] != refresh_claims["jti"]


async def test_refresh_issues_new_access_token(auth_client: AsyncClient) -> None:
    _, refresh = await _login_tokens(auth_client)
    resp = await auth_client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    claims = decode_token(resp.json()["access_token"], TEST_SIGNING_KEY)
    assert claims["type"] == "access"
    assert claims["role"] == "player"
    assert claims["exp"] - claims["iat"] == ACCESS_TTL_SECONDS


async def test_refresh_rejects_access_token(auth_client: AsyncClient) -> None:
    """An access token cannot be used at /auth/refresh (type=access)."""
    access, _ = await _login_tokens(auth_client)
    resp = await auth_client.post("/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


async def test_refresh_rejects_expired_token(auth_client: AsyncClient) -> None:
    await auth_client.post("/auth/register", json=_register_body())
    login = await auth_client.post("/auth/jwt/login", data=_login_form())
    tenant_id = decode_token(login.json()["access_token"], TEST_SIGNING_KEY)["sub"]
    past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=31)
    expired = create_refresh_token(
        tenant_id=uuid.UUID(tenant_id),
        role="player",
        signing_key=TEST_SIGNING_KEY,
        now=past,
    )
    resp = await auth_client.post("/auth/refresh", json={"refresh_token": expired})
    assert resp.status_code == 401


async def test_logout_then_refresh_is_rejected(auth_client: AsyncClient) -> None:
    _, refresh = await _login_tokens(auth_client)
    logout = await auth_client.post("/auth/logout", json={"refresh_token": refresh})
    assert logout.status_code == 204
    # The denylisted refresh token can no longer mint access tokens.
    resp = await auth_client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


async def test_logout_writes_session_revoked_audit_row(
    auth_client: AsyncClient,
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, refresh = await _login_tokens(auth_client)
    jti = decode_token(refresh, TEST_SIGNING_KEY)["jti"]
    await auth_client.post("/auth/logout", json={"refresh_token": refresh})

    async with app_session_factory() as session:
        rows = (
            await session.execute(text("SELECT action, target FROM audit_log"))
        ).all()
    assert any(r.action == "session.revoked" and r.target == jti for r in rows)


async def test_logout_invalid_token_returns_401(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        "/auth/logout", json={"refresh_token": "not-a-real-token"}
    )
    assert resp.status_code == 401


# ── Guest (access-only) + NULL-column verification (commit 4) ──────────────────


async def test_guest_issues_access_only_token(auth_client: AsyncClient) -> None:
    resp = await auth_client.post("/auth/guest")
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" not in body  # access-only: guests are ephemeral
    claims = decode_token(body["access_token"], TEST_SIGNING_KEY)
    assert claims["type"] == "access"
    assert claims["role"] == "player"
    uuid.UUID(claims["sub"])  # a valid guest tenant id


async def test_guest_row_has_null_credentials_and_is_guest(
    auth_client: AsyncClient,
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    resp = await auth_client.post("/auth/guest")
    tenant_id = decode_token(resp.json()["access_token"], TEST_SIGNING_KEY)["sub"]
    async with app_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT email, hashed_password, is_guest, guest_expires_at "
                    "FROM tenants WHERE id = :id"
                ),
                {"id": tenant_id},
            )
        ).one()
    assert row.email is None
    assert row.hashed_password is None
    assert row.is_guest is True
    assert row.guest_expires_at is not None


async def test_guest_tenant_inserts_with_null_credentials(
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Direct DB proof (carried-forward note 1): the SQLAlchemyBaseUserTableUUID
    inheritance did NOT make email/hashed_password NOT NULL — a guest INSERTs."""
    tenant_id = uuid.uuid4()
    async with app_session_factory() as session:
        session.add(Tenant(id=tenant_id, is_guest=True))  # NULL email/password
        await session.commit()  # must NOT raise — columns are nullable

    async with app_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT email, hashed_password FROM tenants WHERE id = :id"),
                {"id": str(tenant_id)},
            )
        ).one()
    assert row.email is None
    assert row.hashed_password is None


# ── auth.login audit (Phase 4.1b) ─────────────────────────────────────────────


async def test_login_writes_auth_login_audit_row(
    auth_client: AsyncClient,
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await auth_client.post("/auth/register", json=_register_body())
    await auth_client.post("/auth/jwt/login", data=_login_form())
    async with app_session_factory() as session:
        actions = (
            (await session.execute(text("SELECT action FROM audit_log")))
            .scalars()
            .all()
        )
    assert "auth.login" in actions


async def test_guest_writes_auth_login_audit_row(
    auth_client: AsyncClient,
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await auth_client.post("/auth/guest")
    async with app_session_factory() as session:
        rows = (
            await session.execute(text("SELECT action, target FROM audit_log"))
        ).all()
    assert any(r.action == "auth.login" and r.target == "guest" for r in rows)
