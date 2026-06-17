"""Corpus version listing (Phase 5.1) — powers the portal's version dropdown."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import rag_chunks as rag_chunks_repo


async def list_versions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    """The corpus's distinct game versions. The corpus is shared (D-005) — no
    RLS, no tenant context — so a plain session suffices."""
    async with session_factory() as session:
        return await rag_chunks_repo.distinct_game_versions(session)
