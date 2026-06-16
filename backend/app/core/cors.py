"""CORS for the browser surfaces (Phase 5.1).

The React portal (``frontend-user/``, :5173) is the first BROWSER client — the
game-client mod is C# and never triggers CORS, so the API was never configured
for a browser origin. This adds an explicit allow-list.

Locked to specific origins — NEVER ``["*"]``: a wildcard CORS origin is a
security smell and contradicts the tenant-isolation posture (it would let any
site drive a logged-in user's authed requests). Bearer tokens travel in the
``Authorization`` header (not cookies), so ``allow_credentials`` stays False.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_cors(app: FastAPI, origins: list[str]) -> None:
    """Add CORSMiddleware locked to *origins*. Rejects an empty list or ``*``."""
    if not origins or "*" in origins:
        raise ValueError(
            "CORS origins must be an explicit allow-list, never '*' (security)."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # Bearer in the Authorization header, not cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
