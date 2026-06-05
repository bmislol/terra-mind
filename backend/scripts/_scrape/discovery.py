"""Wiki page discovery: allpages enumeration + symmetric diff against disk."""

import json
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from scripts._scrape.api import RATE_SLEEP, get_json

# Only scrape the Main namespace (0).
_NAMESPACE = 0
_ALLPAGES_LIMIT = 500


def _allpages_params(continue_token: str | None) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "action": "query",
        "list": "allpages",
        "apnamespace": _NAMESPACE,
        "apfilterredir": "nonredirects",
        "aplimit": _ALLPAGES_LIMIT,
        "format": "json",
    }
    if continue_token is not None:
        params["apcontinue"] = continue_token
    return params


def fetch_all_page_ids(
    api_base: str,
    client: httpx.Client,
    checkpoint_dir: Path,
) -> list[dict[str, Any]]:
    """Run a fresh list=allpages pass. Always starts from scratch (option b).

    Returns a list of {page_id, title} dicts for all non-redirect NS-0 pages.
    The checkpoint file is rewritten on successful completion; on mid-run crash
    it is deleted so the next invocation starts clean (no partial reads).
    """
    index_path = checkpoint_dir / "pages_index.jsonl"

    # Clear any partial index from a prior crashed run before starting.
    if index_path.exists():
        index_path.unlink()

    pages: list[dict[str, Any]] = []
    continue_token: str | None = None

    while True:
        params = _allpages_params(continue_token)
        data = get_json(client, api_base, params)

        batch = data.get("query", {}).get("allpages", [])
        for entry in batch:
            pages.append({"page_id": entry["pageid"], "title": entry["title"]})

        # Check for continuation.
        cont = data.get("continue", {})
        continue_token = cont.get("apcontinue")

        time.sleep(RATE_SLEEP)

        if continue_token is None:
            break

    # Write final index atomically.
    tmp = index_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for page in pages:
            fh.write(json.dumps(page) + "\n")
    tmp.replace(index_path)

    return pages


class DiffResult:
    def __init__(
        self,
        new_ids: set[int],
        unchanged_ids: set[int],
        disappeared_ids: set[int],
    ) -> None:
        self.new_ids = new_ids
        self.unchanged_ids = unchanged_ids
        self.disappeared_ids = disappeared_ids


def compute_diff(
    wiki_pages: list[dict[str, Any]],
    pages_dir: Path,
    checkpoint_dir: Path,
) -> DiffResult:
    """Compute symmetric diff between wiki page IDs and already-fetched files.

    Disappeared pages are moved to .checkpoint/orphaned/ and excluded from
    future manifest computation.
    """
    wiki_ids = {p["page_id"] for p in wiki_pages}
    disk_ids = {
        int(f.stem) for f in pages_dir.glob("*.json") if not f.name.endswith(".tmp")
    }

    new_ids = wiki_ids - disk_ids
    unchanged_ids = wiki_ids & disk_ids
    disappeared_ids = disk_ids - wiki_ids

    if disappeared_ids:
        orphaned_dir = checkpoint_dir / "orphaned"
        orphaned_dir.mkdir(exist_ok=True)
        for pid in disappeared_ids:
            src = pages_dir / f"{pid}.json"
            if src.exists():
                shutil.move(str(src), orphaned_dir / f"{pid}.json")

    return DiffResult(
        new_ids=new_ids,
        unchanged_ids=unchanged_ids,
        disappeared_ids=disappeared_ids,
    )
