"""Corpus build logic — chunk + embed + upsert the cached wiki corpus.

Lives in ``app/`` (not ``scripts/``) so it is importable by both the CLI
(``scripts/build_corpus.py``) **and** the re-rag worker (``app/jobs/rerag.py``)
without an app→scripts layering inversion — and so the worker image, which ships
``app/`` but not ``scripts/``, actually has it (Phase 5.3).

Reads ``data/raw/<version>/pages/`` + ``cargo/`` — it does **not** scrape —
chunks + embeds + upserts into ``rag_chunks`` and writes
``chunk_count``/``embedding_model``/``embedding_dim`` back to ``manifest.json``.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable
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


# ── Progress reporting ────────────────────────────────────────────────────────

# A progress sink: ``(stage, done, total)``. The default prints (preserving the
# CLI's behaviour); the re-rag worker (Phase 5.3) passes a callback that writes
# to Redis + the rerag_jobs row so the operator can watch a build stream live.
ProgressFn = Callable[[str, int, int], None]


def _print_progress(stage: str, done: int, total: int) -> None:
    """Default progress sink — prints, the way the CLI always has."""
    if total:
        pct = int(done / total * 100)
        print(f"[corpus] {stage}: {done}/{total} ({pct}%)")
    else:
        print(f"[corpus] {stage}…")


def sync_db_url(db_url: str) -> str:
    """Rewrite the app's async DSN to a SYNC psycopg (v3) DSN for this build.

    The app connects with ``asyncpg``; the build is sync. Use ``psycopg`` (v3)
    **explicitly** — the bare ``postgresql://`` form defaults to the psycopg2
    dialect, and psycopg2 is not a dependency (only ``psycopg[binary]`` is), so an
    unqualified URL would fail to import a driver. Non-Postgres URLs (e.g. the
    SQLite used in tests) pass through untouched.
    """
    for prefix in ("postgresql+asyncpg://", "postgresql://"):
        if db_url.startswith(prefix):
            return "postgresql+psycopg://" + db_url[len(prefix) :]
    return db_url


# ── Build ──────────────────────────────────────────────────────────────────────


def run_build(
    version: str,
    db_url: str,
    *,
    force: bool = False,
    progress: ProgressFn = _print_progress,
) -> int:
    """Chunk + embed + upsert the cached corpus for ``version`` into pgvector.

    Reads ``data/raw/<version>/`` (pages + cargo) — it does **not** scrape — and
    reports through ``progress(stage, done, total)`` as it goes (``loading`` while
    the embedding model starts, then ``embedding`` per page). The CLI passes the
    printing default; the re-rag worker passes a Redis/DB-writing callback.

    **Retry-safety (D-033).** With ``force=False`` — the default, and the *only*
    way the re-rag worker calls this — every chunk is written via the idempotent
    ``ON CONFLICT (page_id, chunk_index, game_version) DO UPDATE`` upsert
    (``_UPSERT_SQL``), so a re-run resumes/overwrites cleanly: no duplicates, no
    half-version, the version stays queryable throughout. ``force=True`` (CLI
    ``--force`` only) does a destructive delete-then-insert and is **not**
    retry-safe (a mid-run death leaves a half-deleted version); the worker never
    sets it.

    Returns ``0`` on success, ``1`` on a missing/invalid corpus on disk.
    """
    raw_dir = _DATA_ROOT / version
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
    progress("loading", 0, 0)
    print("[corpus] Loading embedding model…")
    embedder = Embedder()
    print(f"[corpus] Model ready: {embedder.model_name} dim={embedder.dim}")

    engine = sa.create_engine(sync_db_url(db_url))

    with engine.begin() as conn:
        if force:
            delete_result = conn.execute(
                text("DELETE FROM rag_chunks WHERE game_version = :v"),
                {"v": version},
            )
            deleted = delete_result.rowcount
            print(f"[corpus] --force: deleted {deleted} existing chunks.")

    # Process pages.
    total_chunks = 0
    cargo_only_count = 0
    total_pages = len(page_files)
    progress("embedding", 0, total_pages)

    for page_num, page_file in enumerate(page_files, 1):
        page_data: dict[str, Any] = json.loads(page_file.read_text(encoding="utf-8"))
        chunks, is_cargo_only = chunk_page(
            page_data,
            game_version=version,
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

        if page_num % 50 == 0 or page_num == total_pages:
            progress("embedding", page_num, total_pages)

    print(
        f"[corpus] Done. {total_pages} pages, {total_chunks} chunks, "
        f"cargo_stats_pages={cargo_only_count}, "
        f"model={embedder.model_name} dim={embedder.dim}"
    )

    _update_manifest(raw_dir, total_chunks, embedder.model_name, embedder.dim)
    return 0
