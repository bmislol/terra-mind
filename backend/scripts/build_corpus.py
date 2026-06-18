"""Corpus build CLI — a thin wrapper over ``app.rag.corpus_build.run_build``.

Usage:
    uv run python -m scripts.build_corpus --version 1.4.4.9 [--db-url URL] [--force]

The build logic lives in ``app/rag/corpus_build.py`` so the re-rag worker can
import it too (Phase 5.3); this module is just the argparse front-end.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.rag.corpus_build import run_build


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
        help="Delete all rag_chunks for this game_version before inserting "
        "(NOT retry-safe — host-side manual use only; the re-rag worker never "
        "uses it, D-033).",
    )
    args = parser.parse_args(argv)

    if not args.db_url:
        print("[corpus] ERROR: --db-url or DATABASE_URL required.", file=sys.stderr)
        return 1

    return run_build(args.version, args.db_url, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
