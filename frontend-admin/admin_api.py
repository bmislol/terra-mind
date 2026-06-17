"""Backend client for the admin bench — all calls are SERVER-SIDE (httpx from the
Streamlit process, not the browser), so no CORS applies (not a browser origin).

Login is form-encoded (`OAuth2PasswordRequestForm`); everything else is JSON.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = httpx.Timeout(30.0)


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _detail(resp: httpx.Response) -> str:
    """Readable error from a FastAPI body (never raw JSON to the operator)."""
    try:
        data = resp.json()
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        return json.dumps(detail) if detail is not None else resp.text
    except Exception:
        return f"HTTP {resp.status_code}"


def token_role(token: str) -> str | None:
    """Read the `role` claim from a JWT WITHOUT verifying (UI gating only — the
    backend's require_operator is the real gate; a forged role still 403s there)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:
        return None


def login(email: str, password: str) -> str:
    resp = httpx.post(
        f"{API_BASE}/auth/jwt/login",
        data={"username": email, "password": password},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _detail(resp))
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ask(
    token: str,
    *,
    message: str,
    state: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message, "state": state}
    if session_id:
        body["session_id"] = session_id
    resp = httpx.post(
        f"{API_BASE}/bot/ask", json=body, headers=_auth(token), timeout=_TIMEOUT
    )
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _detail(resp))
    return dict(resp.json())


def versions() -> list[str]:
    resp = httpx.get(f"{API_BASE}/versions", timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _detail(resp))
    return list(resp.json()["versions"])


def tenants(token: str) -> list[dict[str, Any]]:
    resp = httpx.get(f"{API_BASE}/admin/tenants", headers=_auth(token), timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _detail(resp))
    return list(resp.json())


def audit_log(token: str) -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{API_BASE}/admin/audit-log", headers=_auth(token), timeout=_TIMEOUT
    )
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _detail(resp))
    return list(resp.json())
