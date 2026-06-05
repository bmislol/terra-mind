"""Wiki scraper entrypoint.

Usage:
    uv run python -m scripts.scrape_wiki --version 1.4.4.9 [--force]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from scripts._scrape.api import USER_AGENT, make_client
from scripts._scrape.discovery import compute_diff, fetch_all_page_ids
from scripts._scrape.fetcher import IncompleteCorpusError, fetch_pages
from scripts._scrape.manifest import write_manifest
from scripts._scrape.robots import RobotsTxtError, check_robots

API_BASE = "https://terraria.wiki.gg/api.php"

# Relative to backend/ (the working directory when invoked via uv run).
_DATA_ROOT = Path("data/raw")


def _raw_dir(version: str) -> Path:
    return _DATA_ROOT / version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape terraria.wiki.gg via the MediaWiki API."
    )
    parser.add_argument(
        "--version", required=True, help="game_version tag, e.g. 1.4.4.9"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete data/raw/<version>/ and start from scratch.",
    )
    args = parser.parse_args(argv)

    raw_dir = _raw_dir(args.version)
    checkpoint_dir = raw_dir / ".checkpoint"
    pages_dir = raw_dir / "pages"
    failed_path = checkpoint_dir / "failed.jsonl"

    if args.force and raw_dir.exists():
        print(f"[scrape] --force: removing {raw_dir}")
        shutil.rmtree(raw_dir)

    raw_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    with make_client() as client:
        # 1. robots.txt check.
        try:
            check_robots(API_BASE, USER_AGENT, client)
        except RobotsTxtError as exc:
            print(f"[scrape] ABORT: {exc}", file=sys.stderr)
            return 1

        # 2. Discovery — always re-runs from scratch.
        print("[scrape] Running discovery (list=allpages)…")
        wiki_pages = fetch_all_page_ids(API_BASE, client, checkpoint_dir)
        print(f"[scrape] Discovery complete: {len(wiki_pages)} pages on wiki")

        # 3. Symmetric diff vs. disk.
        diff = compute_diff(wiki_pages, pages_dir, checkpoint_dir)
        print(
            f"[scrape] New: {len(diff.new_ids)}  "
            f"Unchanged: {len(diff.unchanged_ids)}  "
            f"Disappeared: {len(diff.disappeared_ids)}"
        )
        if diff.disappeared_ids:
            print(
                f"[scrape] {len(diff.disappeared_ids)} orphaned page(s) moved to "
                f"{checkpoint_dir / 'orphaned'}"
            )

        # 4. Fetch new pages.
        if diff.new_ids:
            print(f"[scrape] Fetching {len(diff.new_ids)} new page(s)…")
            try:
                fetch_pages(API_BASE, client, diff.new_ids, pages_dir, checkpoint_dir)
            except IncompleteCorpusError as exc:
                print(f"[scrape] ERROR: {exc}", file=sys.stderr)
                return 1
        else:
            print("[scrape] Nothing to fetch.")

        # 5. Write manifest.
        try:
            manifest_path = write_manifest(raw_dir, args.version, API_BASE, failed_path)
        except IncompleteCorpusError as exc:
            print(f"[scrape] ERROR: {exc}", file=sys.stderr)
            return 1

        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(
            f"[scrape] Done. pages={m['page_count']} sha256={m['raw_sha256'][:16]}… "
            f"→ {manifest_path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
