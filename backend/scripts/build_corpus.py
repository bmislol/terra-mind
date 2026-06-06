"""Corpus build entrypoint.

Usage:
    uv run python -m scripts.build_corpus --version 1.4.4.9 [--db-url URL] [--force]

Reads data/raw/<version>/pages/ and cargo/, chunks + embeds, upserts into
rag_chunks, then writes chunk_count/embedding_model/embedding_dim to
manifest.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

from app.rag.chunker import chunk_id, chunk_page
from app.rag.embedder import Embedder
from app.rag.models import ChunkRecord

_DATA_ROOT = Path("data/raw")


# ── DB upsert ─────────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO rag_chunks
    (id, page_id, chunk_index, revision_id, source_url,
     game_version, page_title, section, content, embedding, created_at)
VALUES
    (:id, :page_id, :chunk_index, :revision_id, :source_url,
     :game_version, :page_title, :section, :content, :embedding, :created_at)
ON CONFLICT (page_id, chunk_index, game_version)
DO UPDATE SET
    content      = EXCLUDED.content,
    embedding    = EXCLUDED.embedding,
    revision_id  = EXCLUDED.revision_id,
    page_title   = EXCLUDED.page_title,
    section      = EXCLUDED.section,
    source_url   = EXCLUDED.source_url
"""


def _upsert_chunks(
    conn: sa.engine.Connection,
    chunks: list[ChunkRecord],
    embeddings: Any,
) -> None:
    for i, chunk in enumerate(chunks):
        vec = embeddings[i].tolist()
        conn.execute(
            text(_UPSERT_SQL),
            {
                "id": str(
                    chunk_id(chunk.page_id, chunk.chunk_index, chunk.game_version)
                ),
                "page_id": chunk.page_id,
                "chunk_index": chunk.chunk_index,
                "revision_id": chunk.revision_id,
                "source_url": chunk.source_url,
                "game_version": chunk.game_version,
                "page_title": chunk.page_title,
                "section": chunk.section,
                "content": chunk.content,
                "embedding": f"[{','.join(str(x) for x in vec)}]",
                "created_at": datetime.now(UTC),
            },
        )


# ── Orphan recipes ───────────────────────────────────────────────────────────


def _write_orphan_recipes(
    cargo_recipes: dict[str, list[dict[str, str]]],
    known_pages: set[str],
    orphan_path: Path,
) -> int:
    """Write Recipes rows whose result has no matching wiki page to orphan_path.

    Deletes any pre-existing file first (idempotent).  Returns the row count.
    """
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.unlink(missing_ok=True)
    count = 0
    for result, rows in cargo_recipes.items():
        if result and result not in known_pages:
            with orphan_path.open("a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            count += len(rows)
    return count


# ── Manifest update ───────────────────────────────────────────────────────────


def _update_manifest(
    raw_dir: Path,
    chunk_count: int,
    model_name: str,
    dim: int,
) -> None:
    manifest_path = raw_dir / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chunk_count"] = chunk_count
    manifest["embedding_model"] = model_name
    manifest["embedding_dim"] = dim
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chunk, embed, and upsert the Terraria wiki corpus into pgvector."
    )
    parser.add_argument(
        "--version", required=True, help="game_version tag, e.g. 1.4.4.9"
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres connection URL (defaults to DATABASE_URL env var).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete all rag_chunks for this game_version before inserting.",
    )
    args = parser.parse_args(argv)

    if not args.db_url:
        print("[corpus] ERROR: --db-url or DATABASE_URL required.", file=sys.stderr)
        return 1

    raw_dir = _DATA_ROOT / args.version
    pages_dir = raw_dir / "pages"
    cargo_dir = raw_dir / "cargo"
    manifest_path = raw_dir / "manifest.json"
    orphan_path = cargo_dir / "orphan_recipes.jsonl"

    # Validate inputs.
    for required in (pages_dir, manifest_path):
        if not required.exists():
            print(
                f"[corpus] ERROR: {required} not found. "
                "Run scrape_wiki.py (and scrape_cargo.py) first.",
                file=sys.stderr,
            )
            return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("cargo_raw_sha256"):
        print(
            "[corpus] ERROR: manifest.json missing cargo_* fields. "
            "Run scrape_cargo.py first.",
            file=sys.stderr,
        )
        return 1

    # Load Cargo dicts.
    items_path = cargo_dir / "items.json"
    recipes_path = cargo_dir / "recipes.json"

    cargo_items: dict[str, dict[str, str]] = {}
    if items_path.exists():
        for row in json.loads(items_path.read_text(encoding="utf-8")):
            page_name = row.get("_pageName", "")
            if page_name:
                cargo_items[page_name] = row

    cargo_recipes: dict[str, list[dict[str, str]]] = defaultdict(list)
    known_pages: set[str] = set()
    if recipes_path.exists():
        for row in json.loads(recipes_path.read_text(encoding="utf-8")):
            cargo_recipes[row.get("result", "")].append(row)

    # Load page titles to detect orphan recipes.
    page_files = sorted(pages_dir.glob("*.json"))
    for pf in page_files:
        data: dict[str, Any] = json.loads(pf.read_text(encoding="utf-8"))
        known_pages.add(data.get("title", ""))

    # Log orphan recipes (result with no wiki page).
    orphan_count = _write_orphan_recipes(cargo_recipes, known_pages, orphan_path)

    print(f"[corpus] Pages: {len(page_files)}")
    recipe_total = sum(len(v) for v in cargo_recipes.values())
    print(f"[corpus] Cargo items: {len(cargo_items)}  recipes: {recipe_total}")
    if orphan_count:
        print(f"[corpus] Orphan recipes (no wiki page): {orphan_count} → {orphan_path}")

    # Embedder startup.
    print("[corpus] Loading embedding model…")
    embedder = Embedder()
    print(f"[corpus] Model ready: {embedder.model_name} dim={embedder.dim}")

    # DB connection.
    db_url = args.db_url
    # The app uses asyncpg; for this sync script, use psycopg2-style URL.
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    engine = sa.create_engine(db_url)

    with engine.begin() as conn:
        if args.force:
            delete_result = conn.execute(
                text("DELETE FROM rag_chunks WHERE game_version = :v"),
                {"v": args.version},
            )
            deleted = delete_result.rowcount
            print(f"[corpus] --force: deleted {deleted} existing chunks.")

    # Process pages.
    total_chunks = 0
    cargo_only_count = 0

    for page_num, page_file in enumerate(page_files, 1):
        page_data: dict[str, Any] = json.loads(page_file.read_text(encoding="utf-8"))
        chunks, is_cargo_only = chunk_page(
            page_data,
            game_version=args.version,
            cargo_items=cargo_items,
            cargo_recipes=cargo_recipes,
        )
        if not chunks:
            continue

        if is_cargo_only:
            cargo_only_count += 1

        embed_texts = [c.embed_text for c in chunks]
        embeddings = embedder.encode(embed_texts)

        with engine.begin() as conn:
            _upsert_chunks(conn, chunks, embeddings)

        total_chunks += len(chunks)

        if page_num % 50 == 0 or page_num == len(page_files):
            pct = int(page_num / len(page_files) * 100)
            print(f"[corpus] Processed {page_num}/{len(page_files)} pages ({pct}%)")

    print(
        f"[corpus] Done. {len(page_files)} pages, {total_chunks} chunks, "
        f"cargo_stats_pages={cargo_only_count}, "
        f"model={embedder.model_name} dim={embedder.dim}"
    )

    _update_manifest(raw_dir, total_chunks, embedder.model_name, embedder.dim)
    return 0


if __name__ == "__main__":
    sys.exit(main())
