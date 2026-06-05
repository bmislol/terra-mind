"""Manifest computation: raw_sha256 over fetched pages, manifest.json write."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._scrape.fetcher import IncompleteCorpusError


def compute_sha256(pages_dir: Path) -> str:
    """SHA-256 over all fetched page wikitexts, sorted by page_id ascending.

    Algorithm: for each page in page_id order, feed
      str(page_id).encode() + b"\\x00" + wikitext_utf8 + b"\\x00"
    into a running hasher.  Hash is over content only, not JSON serialisation,
    so it is stable across schema additions.
    """
    page_files = sorted(
        (f for f in pages_dir.glob("*.json") if not f.name.endswith(".tmp")),
        key=lambda f: int(f.stem),
    )

    hasher = hashlib.sha256()
    for path in page_files:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        wikitext: str = data.get("wikitext", "")
        page_id: int = data["page_id"]
        hasher.update(str(page_id).encode() + b"\x00")
        hasher.update(wikitext.encode("utf-8") + b"\x00")

    return hasher.hexdigest()


def write_manifest(
    raw_dir: Path,
    game_version: str,
    api_base: str,
    failed_path: Path,
) -> Path:
    """Compute and write manifest.json.  Raises IncompleteCorpusError if failed.jsonl
    is non-empty (guards against accidentally manifesting a partial corpus).
    """
    if failed_path.exists() and failed_path.stat().st_size > 0:
        failed_count = sum(1 for _ in failed_path.open())
        raise IncompleteCorpusError(
            f"Cannot write manifest: {failed_count} page(s) in {failed_path}."
        )

    pages_dir = raw_dir / "pages"
    page_count = sum(1 for f in pages_dir.glob("*.json") if not f.name.endswith(".tmp"))
    raw_sha256 = compute_sha256(pages_dir)

    manifest: dict[str, Any] = {
        "game_version": game_version,
        "source": "https://terraria.wiki.gg",
        "api_base": api_base,
        "scraped_at": datetime.now(UTC).isoformat(),
        "page_count": page_count,
        "raw_sha256": raw_sha256,
    }

    manifest_path = raw_dir / "manifest.json"
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)

    return manifest_path


def read_manifest(raw_dir: Path) -> dict[str, Any] | None:
    """Return the manifest dict if it exists, else None."""
    path = raw_dir / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
