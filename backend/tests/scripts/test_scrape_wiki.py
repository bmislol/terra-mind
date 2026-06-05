"""Unit tests for the wiki scraper. No live network calls."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from scripts._scrape.discovery import compute_diff, fetch_all_page_ids
from scripts._scrape.fetcher import (
    IncompleteCorpusError,
    _build_batches,
    _extract_wikitext,
    _is_disambiguation,
    fetch_pages,
)
from scripts._scrape.manifest import compute_sha256, write_manifest
from scripts._scrape.robots import RobotsTxtError, check_robots

_FIXTURES = Path(__file__).parent / "fixtures"
_API = "https://terraria.wiki.gg/api.php"


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text())  # type: ignore[no-any-return]


# ── discovery ────────────────────────────────────────────────────────────────


@respx.mock
def test_parse_allpages_response(tmp_path: Path) -> None:
    """fetch_all_page_ids returns correct {page_id, title} list from paged response."""
    first = _load("allpages_response.json")
    final = _load("allpages_final.json")

    respx.get(_API, params__contains={"list": "allpages"}).mock(
        side_effect=[
            httpx.Response(200, json=first),
            httpx.Response(200, json=final),
        ]
    )

    checkpoint_dir = tmp_path / ".checkpoint"
    checkpoint_dir.mkdir()

    with httpx.Client() as client:
        pages = fetch_all_page_ids(_API, client, checkpoint_dir)

    titles = {p["title"] for p in pages}
    ids = {p["page_id"] for p in pages}
    assert "Copper Shortsword" in titles
    assert "Megashark" in titles
    assert ids == {101, 102, 103, 104, 105}


@respx.mock
def test_discovery_clears_partial_index_on_restart(tmp_path: Path) -> None:
    """A stale pages_index.jsonl is deleted before discovery re-runs."""
    stale_index = tmp_path / ".checkpoint" / "pages_index.jsonl"
    stale_index.parent.mkdir(parents=True)
    stale_index.write_text('{"page_id": 999, "title": "Stale"}\n')

    final = _load("allpages_final.json")
    respx.get(_API, params__contains={"list": "allpages"}).mock(
        return_value=httpx.Response(200, json=final)
    )

    with httpx.Client() as client:
        pages = fetch_all_page_ids(_API, client, tmp_path / ".checkpoint")

    # Stale entry gone; only fresh results present.
    assert all(p["page_id"] != 999 for p in pages)


def test_symmetric_diff_new_unchanged_disappeared(tmp_path: Path) -> None:
    """compute_diff correctly classifies new, unchanged, and disappeared page IDs."""
    pages_dir = tmp_path / "pages"
    checkpoint_dir = tmp_path / ".checkpoint"
    pages_dir.mkdir()
    checkpoint_dir.mkdir()

    # Pre-populate disk with page IDs 2, 3, 4.
    for pid in (2, 3, 4):
        (pages_dir / f"{pid}.json").write_text(
            json.dumps({"page_id": pid, "title": f"Page{pid}"}), encoding="utf-8"
        )

    # Wiki returns page IDs 1, 2, 3 (4 has disappeared).
    wiki_pages = [
        {"page_id": 1, "title": "PageNew"},
        {"page_id": 2, "title": "Page2"},
        {"page_id": 3, "title": "Page3"},
    ]
    diff = compute_diff(wiki_pages, pages_dir, checkpoint_dir)

    assert diff.new_ids == {1}
    assert diff.unchanged_ids == {2, 3}
    assert diff.disappeared_ids == {4}


def test_disappeared_pages_moved_to_orphaned(tmp_path: Path) -> None:
    """compute_diff moves disappeared page files to .checkpoint/orphaned/."""
    pages_dir = tmp_path / "pages"
    checkpoint_dir = tmp_path / ".checkpoint"
    pages_dir.mkdir()
    checkpoint_dir.mkdir()

    (pages_dir / "4.json").write_text('{"page_id": 4}', encoding="utf-8")

    wiki_pages: list[dict[str, Any]] = []  # page 4 no longer on wiki
    compute_diff(wiki_pages, pages_dir, checkpoint_dir)

    assert not (pages_dir / "4.json").exists()
    assert (checkpoint_dir / "orphaned" / "4.json").exists()


# ── fetcher ───────────────────────────────────────────────────────────────────


def test_extract_wikitext_modern_content_key() -> None:
    """Modern rvslots=main response: wikitext at slots.main.content."""
    data = _load("page_content_modern.json")
    page = data["query"]["pages"]["104"]
    wikitext = _extract_wikitext(page)
    assert "Megashark" in wikitext
    assert "damage = 70" in wikitext


def test_extract_wikitext_legacy_star_key() -> None:
    """Legacy response: wikitext at slots.main['*'] fallback."""
    data = _load("page_content_legacy.json")
    page = data["query"]["pages"]["105"]
    wikitext = _extract_wikitext(page)
    assert "Skeletron" in wikitext


def test_is_disambiguation_detected() -> None:
    assert _is_disambiguation("{{Disambiguation}}\n* [[Skeleton (NPC)]]\n") is True
    assert _is_disambiguation("{{disambiguation}}\n") is True
    assert _is_disambiguation("{{Disambig}}\n") is True


def test_is_disambiguation_false_for_normal_page() -> None:
    assert _is_disambiguation("{{item\n| name = Megashark\n}}\n") is False


def test_build_batches_splits_correctly() -> None:
    ids = list(range(1, 152))  # 151 IDs
    batches = _build_batches(ids)
    assert len(batches) == 4  # ceil(151/50) = 4
    assert len(batches[0]) == 50
    assert len(batches[-1]) == 1


@respx.mock
def test_source_url_from_canonicalurl(tmp_path: Path) -> None:
    """source_url is populated from canonicalurl, not reconstructed from title."""
    pages_dir = tmp_path / "pages"
    checkpoint_dir = tmp_path / ".checkpoint"
    pages_dir.mkdir()
    checkpoint_dir.mkdir()

    content_resp = _load("page_content_modern.json")
    info_resp = _load("page_info.json")

    respx.get(_API, params__contains={"prop": "revisions"}).mock(
        return_value=httpx.Response(200, json=content_resp)
    )
    respx.get(_API, params__contains={"prop": "info"}).mock(
        return_value=httpx.Response(200, json=info_resp)
    )

    with httpx.Client() as client:
        fetch_pages(_API, client, {104}, pages_dir, checkpoint_dir)

    saved = json.loads((pages_dir / "104.json").read_text())
    assert saved["source_url"] == "https://terraria.wiki.gg/wiki/Megashark"


@respx.mock
def test_failed_page_no_manifest(tmp_path: Path) -> None:
    """Batch API error: writes failed.jsonl and raises IncompleteCorpusError."""
    pages_dir = tmp_path / "pages"
    checkpoint_dir = tmp_path / ".checkpoint"
    pages_dir.mkdir()
    checkpoint_dir.mkdir()

    respx.get(_API, params__contains={"prop": "revisions"}).mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )

    with httpx.Client() as client:
        with pytest.raises(IncompleteCorpusError):
            fetch_pages(_API, client, {999}, pages_dir, checkpoint_dir)

    assert (checkpoint_dir / "failed.jsonl").exists()


def test_write_manifest_raises_on_nonempty_failed(tmp_path: Path) -> None:
    """write_manifest raises IncompleteCorpusError if failed.jsonl is non-empty."""
    raw_dir = tmp_path
    pages_dir = raw_dir / "pages"
    pages_dir.mkdir()
    failed_path = raw_dir / ".checkpoint" / "failed.jsonl"
    failed_path.parent.mkdir()
    failed_path.write_text('{"page_id": 1, "error": "timeout"}\n', encoding="utf-8")

    with pytest.raises(IncompleteCorpusError):
        write_manifest(raw_dir, "1.4.4.9", _API, failed_path)

    assert not (raw_dir / "manifest.json").exists()


def test_atomic_write_no_partial_json(tmp_path: Path) -> None:
    """Verify that write path uses .tmp + os.replace (no partial .json on disk)."""
    from scripts._scrape.fetcher import _write_page_json

    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()

    page: dict[str, Any] = {
        "page_id": 42,
        "title": "Test",
        "namespace": 0,
        "revision_id": 1,
        "timestamp": "2024-01-01T00:00:00Z",
        "source_url": "https://terraria.wiki.gg/wiki/Test",
        "wikitext": "Test content.",
        "is_disambiguation": False,
    }
    _write_page_json(pages_dir, page)

    # Final file exists, no leftover .tmp
    assert (pages_dir / "42.json").exists()
    assert not list(pages_dir.glob("*.tmp"))

    saved = json.loads((pages_dir / "42.json").read_text())
    assert saved["title"] == "Test"


# ── manifest ─────────────────────────────────────────────────────────────────


def test_raw_sha256_deterministic(tmp_path: Path) -> None:
    """Same pages in any iteration order produce the same SHA-256."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()

    pages = [
        {"page_id": 1, "wikitext": "Alpha content."},
        {"page_id": 2, "wikitext": "Beta content."},
        {"page_id": 3, "wikitext": "Gamma content."},
    ]
    # Write in mixed order.
    for p in [pages[2], pages[0], pages[1]]:
        (pages_dir / f"{p['page_id']}.json").write_text(json.dumps(p), encoding="utf-8")

    h1 = compute_sha256(pages_dir)
    h2 = compute_sha256(pages_dir)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_raw_sha256_changes_on_content_change(tmp_path: Path) -> None:
    """Changing one page's wikitext changes the hash."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()

    page: dict[str, Any] = {"page_id": 1, "wikitext": "Original content."}
    (pages_dir / "1.json").write_text(json.dumps(page), encoding="utf-8")
    h1 = compute_sha256(pages_dir)

    page["wikitext"] = "Changed content."
    (pages_dir / "1.json").write_text(json.dumps(page), encoding="utf-8")
    h2 = compute_sha256(pages_dir)

    assert h1 != h2


def test_raw_sha256_excludes_orphans(tmp_path: Path) -> None:
    """Orphaned pages in .checkpoint/orphaned/ are not included in SHA-256."""
    pages_dir = tmp_path / "pages"
    orphaned_dir = tmp_path / ".checkpoint" / "orphaned"
    pages_dir.mkdir(parents=True)
    orphaned_dir.mkdir(parents=True)

    page: dict[str, Any] = {"page_id": 1, "wikitext": "Active page."}
    (pages_dir / "1.json").write_text(json.dumps(page), encoding="utf-8")
    orphan: dict[str, Any] = {"page_id": 99, "wikitext": "This page disappeared."}
    (orphaned_dir / "99.json").write_text(json.dumps(orphan), encoding="utf-8")

    # compute_sha256 only reads pages_dir, so the orphan is excluded.
    h = compute_sha256(pages_dir)
    # If orphan were included the hash would incorporate page_id 99 in sorted order.
    pages_dir_with_orphan = tmp_path / "pages_with_orphan"
    pages_dir_with_orphan.mkdir()
    (pages_dir_with_orphan / "1.json").write_text(json.dumps(page), encoding="utf-8")
    (pages_dir_with_orphan / "99.json").write_text(json.dumps(orphan), encoding="utf-8")
    h_with = compute_sha256(pages_dir_with_orphan)
    assert h != h_with


# ── robots.txt ───────────────────────────────────────────────────────────────


@respx.mock
def test_robots_txt_permissive_passes() -> None:
    respx.get("https://terraria.wiki.gg/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nDisallow: /w/index.php?*action=edit\n",
        )
    )
    with httpx.Client() as client:
        check_robots(_API, "terra-mind-research/0.1", client)  # must not raise


@respx.mock
def test_robots_txt_blocks_api() -> None:
    respx.get("https://terraria.wiki.gg/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nDisallow: /api.php\n",
        )
    )
    with httpx.Client() as client:
        with pytest.raises(RobotsTxtError):
            check_robots(_API, "terra-mind-research/0.1", client)


@respx.mock
def test_robots_txt_unreachable_is_permissive() -> None:
    """If robots.txt is unreachable, we treat it as permissive (don't abort)."""
    respx.get("https://terraria.wiki.gg/robots.txt").mock(
        side_effect=httpx.ConnectError("unreachable")
    )
    with httpx.Client() as client:
        check_robots(_API, "terra-mind-research/0.1", client)  # must not raise
