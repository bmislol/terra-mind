"""Player preferences domain model (Phase 5.1)."""

from __future__ import annotations

from pydantic import BaseModel


class Preferences(BaseModel):
    """Per-tenant config the portal reads/writes.

    DEFERRED (documented, not wired — DECISIONS P-017): ``selected_version`` is
    STORED and round-tripped, but it is NOT consumed by ``/bot/ask`` retrieval —
    that path uses the mod's live ``state.game_version``. Overriding retrieval
    with a stored preference is a separate, larger change, deferred.
    """

    selected_version: str | None = None
