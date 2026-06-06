"""Unit tests for scripts/refresh_golden_set.py.  No live DB or network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

from app.rag.chunker import chunk_id
from scripts.refresh_golden_set import lookup_chunk_key, rewrite_golden_set

# ── Fixture helpers ───────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE rag_chunks (
    id           TEXT    PRIMARY KEY,
    page_id      INTEGER NOT NULL,
    chunk_index  INTEGER NOT NULL,
    game_version TEXT    NOT NULL
)
"""

# Three rows with random-looking UUIDs (simulating pre-fix corpus).
_SEED_ROWS: list[tuple[str, int, int, str]] = [
    ("aaaaaaaa-0000-0000-0000-000000000001", 10, 0, "1.4.4.9"),
    ("aaaaaaaa-0000-0000-0000-000000000002", 10, 1, "1.4.4.9"),
    ("aaaaaaaa-0000-0000-0000-000000000003", 20, 0, "1.4.4.9"),
]


def _make_db(rows: list[tuple[str, int, int, str]] | None = None) -> sa.engine.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(_SCHEMA))
        for uid, page_id, ci, gv in rows or _SEED_ROWS:
            conn.execute(
                text(
                    "INSERT INTO rag_chunks (id, page_id, chunk_index, game_version)"
                    " VALUES (:id, :pid, :ci, :gv)"
                ),
                {"id": uid, "pid": page_id, "ci": ci, "gv": gv},
            )
    return engine


def _records(*question_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "question": f"Q{i + 1}",
            "ideal_answer": f"A{i + 1}",
            "game_version": "1.4.4.9",
            "ground_truth_chunks": ids,
        }
        for i, ids in enumerate(question_ids)
    ]


# ── lookup_chunk_key ──────────────────────────────────────────────────────────


def test_lookup_returns_correct_key() -> None:
    engine = _make_db()
    with engine.connect() as conn:
        key = lookup_chunk_key(conn, "aaaaaaaa-0000-0000-0000-000000000001")
    assert key == (10, 0, "1.4.4.9")


def test_lookup_returns_none_for_missing_uuid() -> None:
    engine = _make_db()
    with engine.connect() as conn:
        key = lookup_chunk_key(conn, "deadbeef-0000-0000-0000-000000000000")
    assert key is None


# ── rewrite_golden_set ────────────────────────────────────────────────────────


def test_rewrite_substitutes_random_uuids() -> None:
    engine = _make_db()
    uid1 = "aaaaaaaa-0000-0000-0000-000000000001"
    uid2 = "aaaaaaaa-0000-0000-0000-000000000002"
    uid3 = "aaaaaaaa-0000-0000-0000-000000000003"
    records = _records([uid1, uid2], [uid3])

    with engine.connect() as conn:
        new_records, n = rewrite_golden_set(records, conn)

    assert n == 3
    assert new_records[0]["ground_truth_chunks"] == [
        str(chunk_id(10, 0, "1.4.4.9")),
        str(chunk_id(10, 1, "1.4.4.9")),
    ]
    assert new_records[1]["ground_truth_chunks"] == [
        str(chunk_id(20, 0, "1.4.4.9")),
    ]


def test_rewrite_idempotent_on_already_deterministic_ids() -> None:
    """Running rewrite on already-deterministic IDs reports n_substituted == 0."""
    stable_rows = [
        (str(chunk_id(10, 0, "1.4.4.9")), 10, 0, "1.4.4.9"),
        (str(chunk_id(20, 0, "1.4.4.9")), 20, 0, "1.4.4.9"),
    ]
    engine = _make_db(rows=stable_rows)

    records = _records(
        [str(chunk_id(10, 0, "1.4.4.9"))],
        [str(chunk_id(20, 0, "1.4.4.9"))],
    )

    with engine.connect() as conn:
        new_records, n = rewrite_golden_set(records, conn)

    assert n == 0
    assert new_records[0]["ground_truth_chunks"] == records[0]["ground_truth_chunks"]
    assert new_records[1]["ground_truth_chunks"] == records[1]["ground_truth_chunks"]


def test_rewrite_preserves_other_fields() -> None:
    """question, ideal_answer, game_version are passed through unchanged."""
    engine = _make_db()
    records = _records(["aaaaaaaa-0000-0000-0000-000000000001"])
    records[0]["ideal_answer"] = "A custom answer"

    with engine.connect() as conn:
        new_records, _ = rewrite_golden_set(records, conn)

    assert new_records[0]["question"] == "Q1"
    assert new_records[0]["ideal_answer"] == "A custom answer"
    assert new_records[0]["game_version"] == "1.4.4.9"


def test_rewrite_missing_uuid_kept_as_is(capsys: Any) -> None:
    """A UUID absent from the DB is kept with a warning on stderr."""
    engine = _make_db(rows=[])  # empty DB
    records = _records(["deadbeef-0000-0000-0000-000000000000"])

    with engine.connect() as conn:
        new_records, n = rewrite_golden_set(records, conn)

    assert n == 0
    kept = "deadbeef-0000-0000-0000-000000000000"
    assert new_records[0]["ground_truth_chunks"] == [kept]
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "deadbeef" in captured.err


# ── CLI (main) ────────────────────────────────────────────────────────────────


def test_main_rewrites_file(tmp_path: Path) -> None:
    from scripts.refresh_golden_set import main

    # Write a JSONL with two random-UUID entries.
    golden = tmp_path / "eval_rag.jsonl"
    golden.write_text(
        json.dumps(
            {
                "question": "Q1",
                "ideal_answer": "A1",
                "game_version": "1.4.4.9",
                "ground_truth_chunks": ["aaaaaaaa-0000-0000-0000-000000000001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Stand up a minimal SQLite DB the main() function can connect to.
    db_path = tmp_path / "test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(_SCHEMA))
        conn.execute(
            text(
                "INSERT INTO rag_chunks (id, page_id, chunk_index, game_version)"
                " VALUES (:id, :pid, :ci, :gv)"
            ),
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "pid": 10,
                "ci": 0,
                "gv": "1.4.4.9",
            },
        )

    rc = main(["--golden-set", str(golden), "--db-url", f"sqlite:///{db_path}"])
    assert rc == 0

    new_records = [
        json.loads(line) for line in golden.read_text().splitlines() if line.strip()
    ]
    assert new_records[0]["ground_truth_chunks"] == [str(chunk_id(10, 0, "1.4.4.9"))]


def test_main_dry_run_does_not_write(tmp_path: Path) -> None:
    from scripts.refresh_golden_set import main

    golden = tmp_path / "eval_rag.jsonl"
    original_content = (
        json.dumps(
            {
                "question": "Q1",
                "ideal_answer": "A1",
                "game_version": "1.4.4.9",
                "ground_truth_chunks": ["aaaaaaaa-0000-0000-0000-000000000001"],
            }
        )
        + "\n"
    )
    golden.write_text(original_content, encoding="utf-8")

    db_path = tmp_path / "test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(_SCHEMA))
        conn.execute(
            text(
                "INSERT INTO rag_chunks (id, page_id, chunk_index, game_version)"
                " VALUES (:id, :pid, :ci, :gv)"
            ),
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "pid": 10,
                "ci": 0,
                "gv": "1.4.4.9",
            },
        )

    rc = main(
        ["--golden-set", str(golden), "--db-url", f"sqlite:///{db_path}", "--dry-run"]
    )
    assert rc == 0
    # File must be unchanged.
    assert golden.read_text(encoding="utf-8") == original_content
