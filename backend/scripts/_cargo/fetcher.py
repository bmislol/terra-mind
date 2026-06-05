"""Cargo API fetcher: cargoquery pagination with rate limiting and retry."""

import time
from typing import Any

import httpx

from scripts._scrape.api import RATE_SLEEP, get_json

# Cargo's maximum rows per request.
_LIMIT = 500

# Fields to fetch per table.
_ITEMS_FIELDS = ",".join(
    [
        "_pageName",
        "name",
        "itemid",
        "damage",
        "damagetype",
        "defense",
        "knockback",
        "velocity",
        "usetime",
        "critical",
        "hardmode",
        "rare",
        "autoswing",
        "stack",
        "consumable",
        "mana",
        "hheal",
        "mheal",
        "bodyslot",
        "listcat",
        "type",
        "tag",
        "tooltip",
        "sell",
        "placeable",
        "axe",
        "pick",
        "hammer",
        "fishing",
        "bait",
        "buffs",
        "debuffs",
    ]
)

_RECIPES_FIELDS = ",".join(
    [
        "_pageName",
        "result",
        "resultid",
        "amount",
        "station",
        "args",
        "version",
    ]
)


def fetch_cargo_table(
    api_base: str,
    client: httpx.Client,
    table: str,
    fields: str,
) -> list[dict[str, str]]:
    """Fetch all rows from a Cargo table via paginated cargoquery.

    Uses limit=500 + offset pagination.  Sleeps RATE_SLEEP between requests.
    Raises ApiError (with full retry already attempted) on any failure.
    """
    rows: list[dict[str, str]] = []
    offset = 0

    while True:
        params: dict[str, str | int] = {
            "action": "cargoquery",
            "tables": table,
            "fields": fields,
            "limit": _LIMIT,
            "offset": offset,
            "format": "json",
        }
        data = get_json(client, api_base, params)
        batch: list[dict[str, Any]] = data.get("cargoquery", [])

        for entry in batch:
            title_data: dict[str, str] = entry.get("title", {})
            rows.append(
                {k: (v if v is not None else "") for k, v in title_data.items()}
            )

        time.sleep(RATE_SLEEP)

        if len(batch) < _LIMIT:
            # Last page — no more data.
            break
        offset += _LIMIT

    return rows


def fetch_items(api_base: str, client: httpx.Client) -> list[dict[str, str]]:
    return fetch_cargo_table(api_base, client, "Items", _ITEMS_FIELDS)


def fetch_recipes(api_base: str, client: httpx.Client) -> list[dict[str, str]]:
    return fetch_cargo_table(api_base, client, "Recipes", _RECIPES_FIELDS)
