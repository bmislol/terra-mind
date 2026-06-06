"""Rewrite eval_rag.jsonl ground-truth UUIDs to deterministic (uuid5) values.

Run this script ONCE against the live DB **before** `docker compose down -v`.
It looks up each UUID's (page_id, chunk_index, game_version) from rag_chunks,
computes the stable deterministic UUID via::

    uuid5(NAMESPACE_OID, f"{page_id}:{chunk_index}:{game_version}")

— the same formula used by build_corpus.py — and overwrites eval_rag.jsonl
in place with an atomic write.

After this script finishes:
  1. docker compose down -v && docker compose up --build
  2. uv run python -m scripts.build_corpus --version 1.4.4.9
  3. The corpus now has these exact stable UUIDs; the golden set matches.

The golden set never needs a UUID refresh again as long as the corpus content
for each (page_id, chunk_index, game_version) triple is unchanged.

Mapping documented
------------------
For each UUID ``u`` in ground_truth_chunks the lookup is::

    SELECT page_id, chunk_index, game_version
    FROM   rag_chunks
    WHERE  id = :u

Those three values are the inputs to chunk_id().  If a UUID is not found in the
DB the script warns and keeps the original value (so you can diagnose missing
chunks before committing).

Usage::

    DATABASE_URL=postgresql://... uv run python scripts/refresh_golden_set.py
    DATABASE_URL=postgresql://... uv run python scripts/refresh_golden_set.py \\
        --golden-set backend/data/eval/eval_rag.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

from app.rag.chunker import chunk_id

_DEFAULT_GOLDEN_SET = Path(__file__).parent.parent / "data" / "eval" / "eval_rag.jsonl"


# ── Core helpers (importable for unit tests) ──────────────────────────────────


def lookup_chunk_key(
    conn: sa.engine.Connection,
    uuid_str: str,
) -> tuple[int, int, str] | None:
    """Return (page_id, chunk_index, game_version) for a UUID, or None."""
    row = conn.execute(
        text(
            "SELECT page_id, chunk_index, game_version FROM rag_chunks WHERE id = :uid"
        ),
        {"uid": uuid_str},
    ).fetchone()
    if row is None:
        return None
    return (row.page_id, row.chunk_index, row.game_version)


def rewrite_golden_set(
    records: list[dict[str, Any]],
    conn: sa.engine.Connection,
) -> tuple[list[dict[str, Any]], int]:
    """Replace random UUIDs with deterministic ones in a list of JSONL records.

    Returns (new_records, n_substituted).  A UUID that has already been
    stabilised (i.e. it equals chunk_id(...)) is not counted as a substitution.
    UUIDs not found in the DB are kept as-is and a warning is printed to stderr.
    """
    new_records: list[dict[str, Any]] = []
    n_substituted = 0

    for rec in records:
        new_ids: list[str] = []
        for old_id in rec["ground_truth_chunks"]:
            key = lookup_chunk_key(conn, old_id)
            if key is None:
                print(
                    f"WARNING: UUID {old_id!r} not found in rag_chunks"
                    " — kept as-is; check that the corpus is loaded",
                    file=sys.stderr,
                )
                new_ids.append(old_id)
                continue
            page_id, ci, gv = key
            new_id = str(chunk_id(page_id, ci, gv))
            if new_id != old_id:
                n_substituted += 1
            new_ids.append(new_id)
        new_records.append({**rec, "ground_truth_chunks": new_ids})

    return new_records, n_substituted


# ── CLI entry point ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite eval_rag.jsonl UUIDs to deterministic (uuid5) values."
    )
    parser.add_argument(
        "--golden-set",
        default=str(_DEFAULT_GOLDEN_SET),
        help="Path to eval_rag.jsonl (default: backend/data/eval/eval_rag.jsonl).",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres connection URL (defaults to DATABASE_URL env var).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to disk.",
    )
    args = parser.parse_args(argv)

    if not args.db_url:
        print("ERROR: --db-url or DATABASE_URL required.", file=sys.stderr)
        return 1

    golden_path = Path(args.golden_set)
    if not golden_path.exists():
        print(f"ERROR: golden set not found at {golden_path}", file=sys.stderr)
        return 1

    records = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    db_url = args.db_url
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        new_records, n_substituted = rewrite_golden_set(records, conn)

    total_uuids = sum(len(r["ground_truth_chunks"]) for r in records)
    print(
        f"[refresh] {len(records)} questions, {total_uuids} UUIDs — "
        f"{n_substituted} substituted"
    )

    if n_substituted == 0:
        print("[refresh] All UUIDs are already deterministic; nothing to write.")
        return 0

    if args.dry_run:
        print("[refresh] --dry-run: skipping write.")
        for rec, new_rec in zip(records, new_records):
            if rec["ground_truth_chunks"] != new_rec["ground_truth_chunks"]:
                print(f"  Q: {rec['question'][:70]}")
                for old, new in zip(
                    rec["ground_truth_chunks"], new_rec["ground_truth_chunks"]
                ):
                    if old != new:
                        print(f"    {old}  →  {new}")
        return 0

    tmp = golden_path.with_suffix(".tmp")
    tmp.write_text(
        "\n".join(json.dumps(r) for r in new_records) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, golden_path)
    print(f"[refresh] Written: {golden_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
