"""Unit tests for RetrievalPipeline.

These tests mock the SQLAlchemy session so no live DB is needed.  They verify
the pipeline's logic — parameter binding, normalisation, empty-corpus handling,
and result count — not the DB's filtering or the HNSW index recall.

Integration coverage (version filtering, real cosine scores, HNSW recall) is
provided by the eval harness in app/eval/rag/harness.py (pytest.mark.eval).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from app.rag.pipeline import RetrievalPipeline

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_row(game_version: str = "1.4.4.9", dist: float = 0.1) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "page_id": 1,
        "page_title": "Test Page",
        "section": "intro",
        "content": "Some content.",
        "source_url": "https://terraria.wiki.gg/wiki/Test_Page",
        "game_version": game_version,
        "dist": dist,
    }


def _make_pipeline(rows: list[dict[str, Any]]) -> tuple[RetrievalPipeline, MagicMock]:
    """Return a pipeline whose session mock returns *rows* on execute()."""
    # cursor mock
    cursor = MagicMock()
    cursor.mappings.return_value.all.return_value = rows

    # session mock — async context manager
    session = AsyncMock()
    session.execute = AsyncMock(return_value=cursor)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    # session_factory mock
    factory = MagicMock()
    factory.return_value = session

    # Mock embedder — never loads MiniLM, returns a deterministic L2-normalised
    # 384-dim vector so test_retrieval_l2_normalize still passes.
    fake_vec = np.zeros(384, dtype=np.float32)
    fake_vec[0] = 1.0  # L2-norm == 1.0 by construction
    embedder = MagicMock()
    embedder.encode.return_value = np.array([fake_vec])
    embedder.dim = 384

    pipeline = RetrievalPipeline(session_factory=factory, embedder=embedder)
    return pipeline, session


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_dispatches_to_correct_version() -> None:
    """The game_version passed to retrieve() must appear in the SQL params."""
    pipeline, session = _make_pipeline([_make_row(game_version="1.4.4.9")])

    await pipeline.retrieve("Copper Shortsword stats", game_version="1.4.4.9", k=5)

    # session.execute was called once; inspect the params dict
    call_args = session.execute.call_args
    params: dict[str, Any] = call_args[0][1]  # positional arg 1 is the params dict
    assert params["game_version"] == "1.4.4.9"

    # Different version → different param value
    pipeline2, session2 = _make_pipeline([_make_row(game_version="1.4.5.0")])
    await pipeline2.retrieve("something", game_version="1.4.5.0", k=5)
    params2: dict[str, Any] = session2.execute.call_args[0][1]
    assert params2["game_version"] == "1.4.5.0"


@pytest.mark.asyncio
async def test_retrieval_l2_normalize() -> None:
    """The query vector sent to the DB must be L2-normalised (unit norm).

    MiniLM's Embedder already calls normalize_embeddings=True.  This test
    verifies the pipeline doesn't accidentally re-scale the vector.
    """
    pipeline, session = _make_pipeline([])

    captured_params: dict[str, Any] = {}

    async def capture_execute(stmt: Any, params: dict[str, Any]) -> Any:
        captured_params.update(params)
        cursor = MagicMock()
        cursor.mappings.return_value.all.return_value = []
        return cursor

    session.execute = capture_execute

    await pipeline.retrieve("test query", game_version="1.4.4.9", k=5)

    vec_str: str = captured_params["query_vec"]
    # Parse "[f0,f1,...,fn]" back to a float list
    floats = [float(x) for x in vec_str[1:-1].split(",")]
    vec = np.array(floats, dtype=np.float32)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-4, (
        f"query embedding is not unit-normed: norm={np.linalg.norm(vec):.6f}"
    )
    assert len(floats) == 384


@pytest.mark.asyncio
async def test_retrieval_handles_empty_corpus() -> None:
    """An empty rag_chunks result must return [] not raise."""
    pipeline, _ = _make_pipeline([])
    result = await pipeline.retrieve("anything", game_version="1.4.4.9", k=5)
    assert result == []


@pytest.mark.asyncio
async def test_retrieval_k_clamps_to_corpus_size() -> None:
    """If the DB returns fewer rows than k, the result length equals the row count.

    The LIMIT in the SQL caps results; the pipeline must not pad or error.
    """
    rows = [_make_row(dist=0.05 * i) for i in range(10)]
    pipeline, _ = _make_pipeline(rows)

    result = await pipeline.retrieve("something", game_version="1.4.4.9", k=100)
    assert len(result) == 10
    # scores are returned descending (lowest dist → highest score)
    scores = [c.score for c in result]
    assert scores == sorted(scores, reverse=True)
