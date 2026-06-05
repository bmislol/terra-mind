"""Unit tests for scripts/_cargo/.  No live network calls."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from scripts._cargo.fetcher import fetch_cargo_table
from scripts._cargo.manifest import (
    CargoManifestError,
    compute_cargo_sha256,
    merge_cargo_manifest,
)

_API = "https://terraria.wiki.gg/api.php"


# ── Fetcher ───────────────────────────────────────────────────────────────────


def _cargo_response(
    rows: list[dict[str, str]] | list[dict[str, str | None]], page: int = 0
) -> dict[str, Any]:
    return {"cargoquery": [{"title": row} for row in rows]}


@respx.mock
def test_fetch_cargo_table_single_page(tmp_path: Path) -> None:
    """A response with fewer than 500 rows fetches exactly one page."""
    rows = [{"_pageName": f"Item{i}", "name": f"Item {i}"} for i in range(3)]
    respx.get(_API, params__contains={"tables": "Items"}).mock(
        return_value=httpx.Response(200, json=_cargo_response(rows))
    )
    with httpx.Client() as client:
        result = fetch_cargo_table(_API, client, "Items", "_pageName,name")
    assert len(result) == 3
    assert result[0]["_pageName"] == "Item0"


@respx.mock
def test_fetch_cargo_table_pagination(tmp_path: Path) -> None:
    """Exactly 500 rows triggers a second request; fewer than 500 ends pagination."""
    page1 = [{"_pageName": f"Item{i}"} for i in range(500)]
    page2 = [{"_pageName": f"Item{i}"} for i in range(500, 503)]
    respx.get(_API, params__contains={"tables": "Items"}).mock(
        side_effect=[
            httpx.Response(200, json=_cargo_response(page1)),
            httpx.Response(200, json=_cargo_response(page2)),
        ]
    )
    with httpx.Client() as client:
        result = fetch_cargo_table(_API, client, "Items", "_pageName")
    assert len(result) == 503


@respx.mock
def test_fetch_cargo_none_values_replaced_with_empty_string() -> None:
    """None values from the API are replaced with empty string."""
    rows_with_none: list[dict[str, str | None]] = [
        {"_pageName": "Item", "damage": None}
    ]
    respx.get(_API, params__contains={"tables": "Items"}).mock(
        return_value=httpx.Response(200, json=_cargo_response(rows_with_none))
    )
    with httpx.Client() as client:
        result = fetch_cargo_table(_API, client, "Items", "_pageName,damage")
    assert result[0]["damage"] == ""


# ── Manifest ──────────────────────────────────────────────────────────────────


def test_compute_cargo_sha256_deterministic(tmp_path: Path) -> None:
    items = tmp_path / "items.json"
    recipes = tmp_path / "recipes.json"
    items.write_bytes(b'[{"_pageName":"A"}]')
    recipes.write_bytes(b'[{"result":"B"}]')
    h1 = compute_cargo_sha256(items, recipes)
    h2 = compute_cargo_sha256(items, recipes)
    assert h1 == h2
    assert len(h1) == 64


def test_compute_cargo_sha256_changes_on_content_change(tmp_path: Path) -> None:
    items = tmp_path / "items.json"
    recipes = tmp_path / "recipes.json"
    items.write_bytes(b'[{"_pageName":"A"}]')
    recipes.write_bytes(b'[{"result":"B"}]')
    h1 = compute_cargo_sha256(items, recipes)
    items.write_bytes(b'[{"_pageName":"CHANGED"}]')
    h2 = compute_cargo_sha256(items, recipes)
    assert h1 != h2


def test_merge_cargo_manifest_adds_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"game_version": "1.4.4.9", "page_count": 100}),
        encoding="utf-8",
    )
    items_path = tmp_path / "items.json"
    recipes_path = tmp_path / "recipes.json"
    items_path.write_bytes(b'[{"_pageName":"A"}]')
    recipes_path.write_bytes(b'[{"result":"B"}]')

    merge_cargo_manifest(
        tmp_path,
        items_count=6233,
        recipes_count=4221,
        items_path=items_path,
        recipes_path=recipes_path,
    )

    updated = json.loads(manifest_path.read_text())
    assert "cargo_scraped_at" in updated
    assert "cargo_raw_sha256" in updated
    assert updated["cargo_table_counts"] == {"items": 6233, "recipes": 4221}
    # Original fields preserved.
    assert updated["game_version"] == "1.4.4.9"
    assert updated["page_count"] == 100


def test_merge_cargo_manifest_raises_without_existing_manifest(tmp_path: Path) -> None:
    items_path = tmp_path / "items.json"
    recipes_path = tmp_path / "recipes.json"
    items_path.write_bytes(b"[]")
    recipes_path.write_bytes(b"[]")
    with pytest.raises(CargoManifestError, match="manifest.json not found"):
        merge_cargo_manifest(
            tmp_path,
            items_count=0,
            recipes_count=0,
            items_path=items_path,
            recipes_path=recipes_path,
        )
