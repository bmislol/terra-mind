"""Unit tests for scripts/build_corpus.py helpers.  No live DB or network."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import sqlalchemy as sa
from sqlalchemy import text

from app.rag.models import ChunkRecord
from scripts.build_corpus import _UPSERT_SQL, _upsert_chunks, _write_orphan_recipes

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
