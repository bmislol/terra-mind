"""Dense-only retrieval pipeline (D-008, D-019).

Public interface:
    pipeline = RetrievalPipeline(session_factory, embedder)
    chunks   = await pipeline.retrieve(query, game_version="1.4.4.9", k=5)

Design notes:
- async throughout — the API is async; sync embedding would block the event loop.
- Query embedding runs in asyncio.to_thread: MiniLM encodes a short query in
  ~10 ms; thread overhead is ~0.1 ms.  The DB round-trip dominates at ~20–60 ms.
- SQL uses CAST(:query_vec AS vector) so the named param appears once and
  asyncpg compiles it to a single positional $1.  ORDER BY the alias so the
  expression resolves once; the HNSW index is still used (planner resolves alias).
- tenant_id is plumbed for Langfuse span context only — never filters rag_chunks,
  which is shared corpus with no tenant column (D-005).
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

from pgvector import Vector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.tracing import current_trace_var
from app.rag.embedder import Embedder
from app.rag.models import RetrievedChunk

# :query_vec appears once; alias `dist` is referenced in ORDER BY.
# PostgreSQL resolves the alias to the underlying expression before planning,
# so the HNSW index on `embedding` (vector_cosine_ops, D-019) is used.
_RETRIEVE_SQL = text("""
    SELECT id,
           page_id,
           page_title,
           section,
           content,
           source_url,
           game_version,
           (embedding <=> CAST(:query_vec AS vector)) AS dist
    FROM   rag_chunks
    WHERE  game_version = :game_version
    ORDER  BY dist
    LIMIT  :k
""")


class RetrievalPipeline:
    """Wraps the dense retrieval path as a stateful object.

    Holds the session factory and embedder so both are initialised once per
    process (at lifespan startup for the API; once per script run for the
    eval harness).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    async def retrieve(
        self,
        query: str,
        *,
        game_version: str,
        k: int = 5,
        tenant_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top-k most similar chunks for *query* in *game_version*.

        Latency budget (per DECISIONS.md D-019, Phase 2.4):
            embed ~10 ms p50 / ~25 ms p99
            DB    ~20 ms p50 / ~60 ms p99
            total ~32 ms p50 / ~90 ms p99
        """
        t0 = time.monotonic()

        # ── Embed in a thread pool ────────────────────────────────────────────
        # MiniLM's encode() is CPU-bound and synchronous.  run it in a worker
        # thread so we don't block the async event loop.  normalize_embeddings
        # is already True in Embedder, so the returned vector is L2-normalised
        # (cosine similarity == inner product for unit-norm vectors).
        raw_vec = await asyncio.to_thread(lambda: self._embedder.encode([query])[0])
        embed_ms = (time.monotonic() - t0) * 1000

        # Convert to pgvector wire format: "[f0,f1,...,f383]"
        # CAST(:query_vec AS vector) in the SQL handles the type coercion.
        query_vec_str = Vector(raw_vec).to_text()

        # ── Similarity search ─────────────────────────────────────────────────
        t_db = time.monotonic()
        async with self._session_factory() as session:
            cursor = await session.execute(
                _RETRIEVE_SQL,
                {
                    "query_vec": query_vec_str,
                    "game_version": game_version,
                    "k": k,
                },
            )
            rows = cursor.mappings().all()
        db_ms = (time.monotonic() - t_db) * 1000
        total_ms = (time.monotonic() - t0) * 1000

        chunks = [
            RetrievedChunk(
                id=UUID(str(row["id"])),
                page_id=int(row["page_id"]),
                page_title=str(row["page_title"]),
                section=str(row["section"]),
                content=str(row["content"]),
                source_url=str(row["source_url"]),
                game_version=str(row["game_version"]),
                score=float(1.0 - row["dist"]),  # cosine distance → similarity
            )
            for row in rows
        ]

        # ── Langfuse span ─────────────────────────────────────────────────────
        # current_trace_var is None outside a request context (eval harness,
        # scripts).  Guard so the pipeline is usable without FastAPI.
        trace = current_trace_var.get()
        if trace is not None:
            span = trace.span(
                name="rag.retrieve",
                input={
                    "query": query,
                    "game_version": game_version,
                    "tenant_id": tenant_id or "",
                    "k": k,
                },
            )
            span.end(
                output=[
                    {
                        "page_title": c.page_title,
                        "section": c.section,
                        "score": round(c.score, 4),
                    }
                    for c in chunks
                ],
                metadata={
                    "embed_ms": round(embed_ms, 1),
                    "db_query_ms": round(db_ms, 1),
                    "total_ms": round(total_ms, 1),
                },
            )

        return chunks
