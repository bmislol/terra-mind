"""Cargo scraper entrypoint — Items and Recipes tables only.

Usage:
    uv run python -m scripts.scrape_cargo --version 1.4.4.9 [--force]

Mirrors scrape_wiki.py's design: resumable, idempotent, atomic writes,
manifest extension with cargo_*, loud failure + no manifest write on error.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from scripts._cargo.fetcher import fetch_items, fetch_recipes
from scripts._cargo.manifest import CargoManifestError, merge_cargo_manifest
from scripts._scrape.api import USER_AGENT, make_client
from scripts._scrape.robots import RobotsTxtError, check_robots

API_BASE = "https://terraria.wiki.gg/api.php"
_DATA_ROOT = Path("data/raw")


def _cargo_dir(version: str) -> Path:
    return _DATA_ROOT / version / "cargo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape terraria.wiki.gg Cargo tables (Items + Recipes)."
    )
    parser.add_argument(
        "--version", required=True, help="game_version tag, e.g. 1.4.4.9"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete data/raw/<version>/cargo/ and start from scratch.",
    )
    args = parser.parse_args(argv)

    cargo_dir = _cargo_dir(args.version)
    raw_dir = _DATA_ROOT / args.version
    items_path = cargo_dir / "items.json"
    recipes_path = cargo_dir / "recipes.json"

    # Check manifest.json exists (scrape_wiki.py must run first).
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        print(
            f"[cargo] ERROR: manifest.json not found at {manifest_path}. "
            "Run scrape_wiki.py first.",
            file=sys.stderr,
        )
        return 1

    if args.force and cargo_dir.exists():
        print(f"[cargo] --force: removing {cargo_dir}")
        shutil.rmtree(cargo_dir)

    # Idempotent: if cargo_* fields already in manifest and files exist, skip.
    if not args.force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("cargo_raw_sha256")
            and items_path.exists()
            and recipes_path.exists()
        ):
            counts = manifest.get("cargo_table_counts", {})
            print(
                f"[cargo] Already complete "
                f"(items={counts.get('items')}, recipes={counts.get('recipes')}). "
                "Use --force to re-scrape."
            )
            return 0

    cargo_dir.mkdir(parents=True, exist_ok=True)

    with make_client() as client:
        # robots.txt check — same host already cleared by scrape_wiki.py but
        # we check anyway for defensiveness.
        try:
            check_robots(API_BASE, USER_AGENT, client)
        except RobotsTxtError as exc:
            print(f"[cargo] ABORT: {exc}", file=sys.stderr)
            return 1

        # Fetch Items.
        print("[cargo] Fetching Items table…")
        try:
            items = fetch_items(API_BASE, client)
        except Exception as exc:
            print(f"[cargo] ERROR fetching Items: {exc}", file=sys.stderr)
            return 1
        print(f"[cargo] Items: {len(items)} rows")

        # Fetch Recipes.
        print("[cargo] Fetching Recipes table…")
        try:
            recipes = fetch_recipes(API_BASE, client)
        except Exception as exc:
            print(f"[cargo] ERROR fetching Recipes: {exc}", file=sys.stderr)
            return 1
        print(f"[cargo] Recipes: {len(recipes)} rows")

    # Write atomically.
    _write_json_atomic(items_path, items)
    _write_json_atomic(recipes_path, recipes)

    # Merge cargo_* fields into manifest.json.
    try:
        merge_cargo_manifest(
            raw_dir,
            items_count=len(items),
            recipes_count=len(recipes),
            items_path=items_path,
            recipes_path=recipes_path,
        )
    except CargoManifestError as exc:
        print(f"[cargo] ERROR: {exc}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sha = manifest.get("cargo_raw_sha256", "")[:16]
    print(
        f"[cargo] Done. items={len(items)} recipes={len(recipes)} "
        f"sha256={sha}… → {manifest_path}"
    )
    return 0


def _write_json_atomic(path: Path, data: list[dict[str, str]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
