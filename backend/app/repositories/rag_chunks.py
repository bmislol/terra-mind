"""Read-only corpus queries (shared, version-tagged — D-005; no RLS, no tenant)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RagChunk


async def distinct_game_versions(session: AsyncSession) -> list[str]:
    """Distinct ``game_version`` values present in the corpus, sorted ascending."""
    result = await session.execute(
        select(RagChunk.game_version).distinct().order_by(RagChunk.game_version)
    )
    return [row[0] for row in result.all()]
