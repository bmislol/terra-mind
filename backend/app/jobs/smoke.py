"""Smoke job — proves the RQ enqueue → worker → result round-trip.

Phase 5.3, commit 1. A no-op the worker can run so the broker/worker infra is
verifiable on its own, before the real re-rag job (commit 3) lands. It is not
wired to any endpoint — only the round-trip test and a manual ``enqueue`` use it.
"""

from __future__ import annotations


def ping() -> str:
    """Trivial RQ job: return ``"pong"`` so a round-trip can be asserted."""
    return "pong"
