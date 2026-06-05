"""Cargo manifest: cargo_raw_sha256 computation and manifest.json merge."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CargoManifestError(RuntimeError):
    pass


def compute_cargo_sha256(items_path: Path, recipes_path: Path) -> str:
    """SHA-256 over items.json bytes + NUL + recipes.json bytes.

    Stable across re-runs when Cargo content is unchanged.
    """
    hasher = hashlib.sha256()
    hasher.update(items_path.read_bytes())
    hasher.update(b"\x00")
    hasher.update(recipes_path.read_bytes())
    return hasher.hexdigest()


def merge_cargo_manifest(
    raw_dir: Path,
    items_count: int,
    recipes_count: int,
    items_path: Path,
    recipes_path: Path,
) -> None:
    """Merge cargo_* fields into the existing manifest.json.

    Raises CargoManifestError if manifest.json doesn't exist yet
    (scrape_wiki.py must run first).
    """
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        raise CargoManifestError(
            f"manifest.json not found at {manifest_path}. Run scrape_wiki.py first."
        )

    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["cargo_scraped_at"] = datetime.now(UTC).isoformat()
    manifest["cargo_raw_sha256"] = compute_cargo_sha256(items_path, recipes_path)
    manifest["cargo_table_counts"] = {
        "items": items_count,
        "recipes": recipes_count,
    }

    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)
