"""Unit tests for the corpus build logic (app/rag/corpus_build.py).

The build lives in app/ (importable by the CLI and the re-rag worker alike,
Phase 5.3); scripts/build_corpus.py is now just the CLI front-end. No live DB
or network.
"""

import itertools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy import text

import app.rag.corpus_build as build_corpus
from app.rag.corpus_build import _UPSERT_SQL, _upsert_chunks, _write_orphan_recipes
from app.rag.models import ChunkRecord

# ── Upsert correctness ────────────────────────────────────────────────────────

# The six mutable columns that DO UPDATE SET must cover so that a non-force
# rerun overwrites stale rows rather than silently keeping old content.
_MUTABLE_COLUMNS = {
    "section",
    "content",
    "embedding",
    "revision_id",
    "source_url",
    "page_title",
}

# Columns that form the conflict key and must NOT be updated on conflict.
_KEY_COLUMNS = {"page_id", "chunk_index", "game_version"}


def _do_update_clause(sql: str) -> str:
    """Extract the DO UPDATE SET ... portion of an upsert statement."""
    marker = "DO UPDATE SET"
    idx = sql.upper().find(marker)
    assert idx != -1, "SQL has no DO UPDATE SET clause"
    return sql[idx:]


def test_upsert_sql_do_update_contains_all_mutable_columns() -> None:
    """Every mutable rag_chunks column must appear in DO UPDATE SET.

    This is a regression guard: if a column is accidentally dropped from the
    clause, a non-force rerun silently keeps stale content in the DB.
    """
    do_update = _do_update_clause(_UPSERT_SQL)
    for col in _MUTABLE_COLUMNS:
        assert col in do_update, (
            f"'{col}' missing from ON CONFLICT DO UPDATE SET — "
            "non-force reruns will silently keep stale values"
        )


def _make_sqlite_engine() -> sa.engine.Engine:
    """In-memory SQLite engine with a rag_chunks table compatible with _UPSERT_SQL.

    embedding is TEXT here (not vector) — SQLite has no pgvector type, but the
    upsert logic is dialect-agnostic and the ON CONFLICT DO UPDATE syntax is
    identical in SQLite ≥ 3.24 and PostgreSQL.
    """
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text("""
                CREATE TABLE rag_chunks (
                    id          TEXT    PRIMARY KEY,
                    page_id     INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    revision_id INTEGER NOT NULL DEFAULT 0,
                    source_url  TEXT    NOT NULL DEFAULT '',
                    game_version TEXT   NOT NULL,
                    page_title  TEXT    NOT NULL,
                    section     TEXT    NOT NULL DEFAULT '',
                    content     TEXT    NOT NULL,
                    embedding   TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL,
                    UNIQUE (page_id, chunk_index, game_version)
                )
            """)
        )
    return engine


def _chunk(
    section: str,
    content: str,
    page_id: int = 1,
    chunk_index: int = 0,
) -> ChunkRecord:
    return ChunkRecord(
        page_id=page_id,
        chunk_index=chunk_index,
        revision_id=100,
        source_url="https://terraria.wiki.gg/wiki/Megashark",
        game_version="1.4.4.9",
        page_title="Megashark",
        section=section,
        content=content,
        embed_text=f"Megashark — {section}\n{content}",
    )


def _fake_embeddings(n: int) -> np.ndarray[tuple[int, int], np.dtype[np.float32]]:
    return np.zeros((n, 384), dtype=np.float32)


def test_upsert_updates_section_and_content_on_conflict() -> None:
    """ON CONFLICT DO UPDATE SET must overwrite section and content in place.

    Regression test for the re-rag story: a non-force rerun after the chunker
    changes output (e.g. section normalisation, recipe qty fix) must write new
    values into existing rows, not silently keep the old ones.
    """
    engine = _make_sqlite_engine()

    # Initial insert — simulates first build_corpus run.
    initial = _chunk(section="Catatan", content="Old content before fix.")
    with engine.begin() as conn:
        _upsert_chunks(conn, [initial], _fake_embeddings(1))

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT section, content FROM rag_chunks WHERE page_id = 1")
        ).fetchone()
    assert row is not None
    assert row.section == "Catatan"
    assert row.content == "Old content before fix."

    # Re-insert same key with changed section + content — simulates non-force rerun
    # after the misc-normalisation and qty=1 fixes landed.
    updated = _chunk(section="misc", content="New content after fix.")
    with engine.begin() as conn:
        _upsert_chunks(conn, [updated], _fake_embeddings(1))

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT section, content FROM rag_chunks WHERE page_id = 1")
        ).fetchall()

    # Exactly one row — no duplicate inserted.
    assert len(rows) == 1
    # Values reflect the new chunker output.
    assert rows[0].section == "misc", (
        "section not updated — ON CONFLICT DO UPDATE SET may be missing 'section'"
    )
    assert rows[0].content == "New content after fix.", (
        "content not updated — ON CONFLICT DO UPDATE SET may be missing 'content'"
    )


def test_orphan_recipes_file_written_when_orphans_exist(tmp_path: Path) -> None:
    """_write_orphan_recipes writes a file containing orphan rows."""
    cargo_recipes: dict[str, list[dict[str, str]]] = defaultdict(list)
    cargo_recipes["Orphan Item"].append(
        {"result": "Orphan Item", "station": "Work Bench", "args": "Wood¦1"}
    )
    cargo_recipes["Megashark"].append(
        {"result": "Megashark", "station": "Mythril Anvil", "args": "Minishark¦1"}
    )

    known_pages = {"Megashark"}  # Orphan Item has no matching wiki page
    orphan_path = tmp_path / "cargo" / "orphan_recipes.jsonl"

    count = _write_orphan_recipes(cargo_recipes, known_pages, orphan_path)

    assert count == 1
    assert orphan_path.exists()
    lines = orphan_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["result"] == "Orphan Item"


def test_orphan_recipes_file_absent_when_no_orphans(tmp_path: Path) -> None:
    """If all recipes match known pages, the orphan file is not created."""
    cargo_recipes: dict[str, list[dict[str, str]]] = defaultdict(list)
    cargo_recipes["Megashark"].append({"result": "Megashark", "args": "Minishark¦1"})

    known_pages = {"Megashark"}
    orphan_path = tmp_path / "cargo" / "orphan_recipes.jsonl"

    count = _write_orphan_recipes(cargo_recipes, known_pages, orphan_path)

    assert count == 0
    assert not orphan_path.exists()


def test_orphan_recipes_idempotent_rerun(tmp_path: Path) -> None:
    """Re-running _write_orphan_recipes replaces the previous file."""
    cargo_recipes: dict[str, list[dict[str, str]]] = defaultdict(list)
    cargo_recipes["Ghost"].append({"result": "Ghost", "args": "Ectoplasm¦5"})

    known_pages: set[str] = set()
    orphan_path = tmp_path / "orphan_recipes.jsonl"

    _write_orphan_recipes(cargo_recipes, known_pages, orphan_path)
    assert orphan_path.read_text().count("\n") == 1

    # Second call should produce the same single-line file, not append.
    _write_orphan_recipes(cargo_recipes, known_pages, orphan_path)
    assert orphan_path.read_text().count("\n") == 1


# ── run_build progress seam (Phase 5.3 commit 2) ──────────────────────────────

# The same rag_chunks shape as _make_sqlite_engine, but for a file-backed DB so
# run_build (which opens its own engine from the URL) sees the table.
_RAG_CHUNKS_DDL = """
    CREATE TABLE rag_chunks (
        id          TEXT    PRIMARY KEY,
        page_id     INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        revision_id INTEGER NOT NULL DEFAULT 0,
        source_url  TEXT    NOT NULL DEFAULT '',
        game_version TEXT   NOT NULL,
        page_title  TEXT    NOT NULL,
        section     TEXT    NOT NULL DEFAULT '',
        content     TEXT    NOT NULL,
        embedding   TEXT    NOT NULL,
        created_at  TEXT    NOT NULL,
        UNIQUE (page_id, chunk_index, game_version)
    )
"""


class _FakeEmbedder:
    """Stand-in for app.rag.embedder.Embedder — no model download."""

    model_name = "fake-MiniLM"
    dim = 384

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 384), dtype=np.float32)


def test_run_build_threads_progress_and_still_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_build reports (stage, done, total) AND performs the idempotent upsert.

    The chunker + embedder are faked (no model load, no wiki) and the build runs
    against a file-backed SQLite. This proves the new progress seam fires
    (``loading`` then ``embedding`` to 100%) while the build still writes rows —
    behaviour unchanged. ``force`` defaults False → the idempotent-upsert path the
    re-rag worker uses (D-033), never a destructive delete.
    """
    version = "9.9.9.9"
    raw = tmp_path / version
    pages = raw / "pages"
    cargo = raw / "cargo"
    pages.mkdir(parents=True)
    cargo.mkdir(parents=True)
    (raw / "manifest.json").write_text(
        json.dumps({"cargo_raw_sha256": "deadbeef"}), encoding="utf-8"
    )
    (cargo / "items.json").write_text("[]", encoding="utf-8")
    (cargo / "recipes.json").write_text("[]", encoding="utf-8")

    n_pages = 3
    for i in range(n_pages):
        (pages / f"p{i}.json").write_text(
            json.dumps({"title": f"Page {i}"}), encoding="utf-8"
        )

    db_path = tmp_path / "corpus.db"
    db_url = f"sqlite:///{db_path}"
    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(_RAG_CHUNKS_DDL))
    engine.dispose()

    # One chunk per page, with distinct page_ids so all rows are kept.
    counter = itertools.count(1)

    def fake_chunk_page(
        page_data: dict[str, Any],
        *,
        game_version: str,
        cargo_items: dict[str, dict[str, str]],
        cargo_recipes: dict[str, list[dict[str, str]]],
    ) -> tuple[list[ChunkRecord], bool]:
        chunk = ChunkRecord(
            page_id=next(counter),
            chunk_index=0,
            revision_id=1,
            source_url="https://terraria.wiki.gg/wiki/Test",
            game_version=game_version,
            page_title=page_data["title"],
            section="s",
            content="c",
            embed_text="t",
        )
        return [chunk], False

    monkeypatch.setattr(build_corpus, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(build_corpus, "Embedder", _FakeEmbedder)
    monkeypatch.setattr(build_corpus, "chunk_page", fake_chunk_page)

    events: list[tuple[str, int, int]] = []

    def record(stage: str, done: int, total: int) -> None:
        events.append((stage, done, total))

    rc = build_corpus.run_build(version, db_url, progress=record)

    assert rc == 0
    stages = [stage for stage, _, _ in events]
    assert "loading" in stages
    assert "embedding" in stages
    # The embedding stage reaches 100% (done == total).
    embedding_ticks = [
        (done, total) for stage, done, total in events if stage == "embedding"
    ]
    assert embedding_ticks[-1] == (n_pages, n_pages)

    # And the build actually happened — one row per page, via the upsert.
    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM rag_chunks")).scalar()
    engine.dispose()
    assert count == n_pages
