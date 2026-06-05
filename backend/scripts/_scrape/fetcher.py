"""Batch content + canonical-URL fetcher, atomic per-page writes, failed.jsonl."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from scripts._scrape.api import RATE_SLEEP, ApiError, get_json

_BATCH_SIZE = 50

# Wikitext extraction tries modern slot key first, then legacy fallbacks.
_SLOT_KEYS = ("content", "*")


class IncompleteCorpusError(RuntimeError):
    pass


def _extract_wikitext(page_data: dict[str, Any]) -> str:
    revisions = page_data.get("revisions")
    if not revisions:
        return ""
    rev = revisions[0]
    # Modern MediaWiki (1.32+): slots.main.content or slots.main['*']
    slots = rev.get("slots", {})
    main_slot = slots.get("main", {})
    for key in _SLOT_KEYS:
        if key in main_slot:
            return str(main_slot[key])
    # Legacy fallback: top-level '*'
    return str(rev.get("*", ""))


def _is_disambiguation(wikitext: str) -> bool:
    lower = wikitext.lower()
    return "{{disambiguation" in lower or "{{disambig" in lower


def _build_batches(ids: list[int]) -> list[list[int]]:
    return [ids[i : i + _BATCH_SIZE] for i in range(0, len(ids), _BATCH_SIZE)]


def _content_params(page_ids: list[int]) -> dict[str, str | int]:
    return {
        "action": "query",
        "pageids": "|".join(str(pid) for pid in page_ids),
        "prop": "revisions",
        "rvprop": "content|ids|timestamp",
        "rvslots": "main",
        "format": "json",
    }


def _info_params(page_ids: list[int]) -> dict[str, str | int]:
    return {
        "action": "query",
        "pageids": "|".join(str(pid) for pid in page_ids),
        "prop": "info",
        "inprop": "url",
        "format": "json",
    }


def _write_page_json(pages_dir: Path, page: dict[str, Any]) -> None:
    page_id = page["page_id"]
    target = pages_dir / f"{page_id}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)  # atomic on POSIX


def _clean_stale_tmp(pages_dir: Path) -> None:
    for tmp in pages_dir.glob("*.tmp"):
        tmp.unlink(missing_ok=True)


def fetch_pages(
    api_base: str,
    client: httpx.Client,
    page_ids_to_fetch: set[int],
    pages_dir: Path,
    checkpoint_dir: Path,
) -> None:
    """Fetch content + canonical URLs for page_ids_to_fetch; write per-page JSON.

    Pages that exhaust retries are appended to .checkpoint/failed.jsonl.
    Raises IncompleteCorpusError at the end if any failures occurred.
    """
    _clean_stale_tmp(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    failed_path = checkpoint_dir / "failed.jsonl"
    # Clear failed log from any previous run.
    failed_path.unlink(missing_ok=True)

    if not page_ids_to_fetch:
        return

    batches = _build_batches(sorted(page_ids_to_fetch))
    total = len(page_ids_to_fetch)
    fetched = 0

    for batch in batches:
        batch_failed: list[dict[str, Any]] = []

        # Fetch content.
        try:
            content_data = get_json(client, api_base, _content_params(batch))
        except ApiError as exc:
            for pid in batch:
                batch_failed.append(
                    {
                        "page_id": pid,
                        "error": str(exc),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            _append_failed(failed_path, batch_failed)
            time.sleep(RATE_SLEEP)
            continue

        time.sleep(RATE_SLEEP)

        # Fetch canonical URLs for the same batch.
        try:
            info_data = get_json(client, api_base, _info_params(batch))
        except ApiError as exc:
            for pid in batch:
                batch_failed.append(
                    {
                        "page_id": pid,
                        "error": f"info fetch failed: {exc}",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            _append_failed(failed_path, batch_failed)
            time.sleep(RATE_SLEEP)
            continue

        time.sleep(RATE_SLEEP)

        content_pages: dict[str, Any] = content_data.get("query", {}).get("pages", {})
        info_pages: dict[str, Any] = info_data.get("query", {}).get("pages", {})

        for pid in batch:
            key = str(pid)
            page_content = content_pages.get(key, {})
            page_info = info_pages.get(key, {})

            if "missing" in page_content:
                # Page was discovered but no longer exists — treat as failed.
                batch_failed.append(
                    {
                        "page_id": pid,
                        "error": "page missing in content response",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                continue

            wikitext = _extract_wikitext(page_content)
            page_title = page_content.get("title", str(pid))
            fallback_url = f"{api_base.replace('/api.php', '')}/wiki/{page_title}"
            canonical_url: str = page_info.get("canonicalurl", fallback_url)

            revisions = page_content.get("revisions", [{}])
            rev = revisions[0] if revisions else {}

            record: dict[str, Any] = {
                "page_id": pid,
                "title": page_content.get("title", ""),
                "namespace": page_content.get("ns", 0),
                "revision_id": rev.get("revid", 0),
                "timestamp": rev.get("timestamp", ""),
                "source_url": canonical_url,
                "wikitext": wikitext,
                "is_disambiguation": _is_disambiguation(wikitext),
            }
            _write_page_json(pages_dir, record)
            fetched += 1

        if batch_failed:
            _append_failed(failed_path, batch_failed)

        pct = int(fetched / total * 100) if total else 0
        print(f"[scrape] Fetched {fetched}/{total} pages ({pct}%)")

    print(f"[scrape] Fetched {fetched}/{total} pages.")

    if failed_path.exists() and failed_path.stat().st_size > 0:
        failed_count = sum(1 for _ in failed_path.open())
        raise IncompleteCorpusError(
            f"{failed_count} page(s) failed after retries. "
            f"See {failed_path}. Fix and re-run (manifest not written)."
        )


def _append_failed(path: Path, entries: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
