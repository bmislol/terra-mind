"""CORS allow-list (Phase 5.1).

The portal is the first browser client; without CORS the browser blocks every
call. These assert the allow-listed origin gets the header, a stranger doesn't,
and a wildcard origin is rejected outright (never ``*`` — security).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.cors import add_cors

_ORIGIN = "http://localhost:5173"


def _app() -> FastAPI:
    app = FastAPI()
    add_cors(app, [_ORIGIN])

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    return app


async def test_allowed_origin_gets_cors_header() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        resp = await client.get("/ping", headers={"Origin": _ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == _ORIGIN


async def test_disallowed_origin_gets_no_cors_header() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        resp = await client.get("/ping", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_wildcard_origin_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"never '\*'"):
        add_cors(FastAPI(), ["*"])

    with pytest.raises(ValueError):
        add_cors(FastAPI(), [])
