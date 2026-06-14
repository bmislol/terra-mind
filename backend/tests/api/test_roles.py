"""Operator role gate (Phase 4.1a commit 4).

No operator endpoint exists yet (admin routes are Phase 5.2), so this tests the
``require_operator`` dependency through a throwaway route. Proves BOTH
directions — a player token is rejected (403, the security-relevant half) and
an operator token is allowed — plus the missing-token case (401).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_operator
from app.infra.jwt_tokens import create_access_token
from app.infra.vault import AppSecrets
from app.services.auth import AccessContext

_KEY = "test-roles-signing-key-0123456789"


def _token(role: str) -> str:
    return create_access_token(tenant_id=uuid.uuid4(), role=role, signing_key=_KEY)


@pytest.fixture
async def operator_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    @app.get("/operator-only")
    async def operator_only(
        auth: AccessContext = Depends(require_operator),
    ) -> dict[str, str]:
        return {"role": auth.role}

    app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.secrets = AppSecrets(anthropic_api_key="sk-ant-x", jwt_signing_key=_KEY)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("operator", 200), ("player", 403)],
)
async def test_operator_route_enforces_role(
    operator_client: AsyncClient, role: str, expected_status: int
) -> None:
    resp = await operator_client.get(
        "/operator-only", headers={"Authorization": f"Bearer {_token(role)}"}
    )
    assert resp.status_code == expected_status


async def test_operator_route_requires_a_token(operator_client: AsyncClient) -> None:
    resp = await operator_client.get("/operator-only")
    assert resp.status_code == 401
