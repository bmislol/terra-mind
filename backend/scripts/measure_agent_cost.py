"""Measure agent-path latency, token usage, and cost for 10 hard questions.

For each question, POST to /bot/ask with realistic StatePayload and record the
HTTP status, response time, routing decision, and full response body.  Write
a timestamped JSON file and print a summary table.

Token counts come from the Langfuse trace (manual, after this script runs).
The cost_usd column in the summary is populated only when token fields are
provided — otherwise it shows "PENDING".

Haiku pricing constants (claude-haiku-4-5):
    Input:  $0.80 / 1 000 000 tokens
    Output: $4.00 / 1 000 000 tokens

Usage::

    uv run python scripts/measure_agent_cost.py
    uv run python scripts/measure_agent_cost.py --url http://localhost:8000
    uv run python scripts/measure_agent_cost.py --output /tmp/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ── Pricing constants (D-023: claude-haiku-4-5) ───────────────────────────────

HAIKU_INPUT_COST_PER_M = 0.80  # USD per 1 000 000 input tokens
HAIKU_OUTPUT_COST_PER_M = 4.00  # USD per 1 000 000 output tokens


def compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for given token counts."""
    return (
        input_tokens * HAIKU_INPUT_COST_PER_M / 1_000_000
        + output_tokens * HAIKU_OUTPUT_COST_PER_M / 1_000_000
    )


# ── Question fixtures ─────────────────────────────────────────────────────────

QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "Q11",
        "message": "What armor should a Mage use after defeating Plantera?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "hallowed headgear"},
                    {"item_id": 0, "name": "hallowed plate mail"},
                    {"item_id": 0, "name": "hallowed greaves"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "crystal storm"},
            },
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                    "Plantera",
                ],
                "biome": "underground jungle",
            },
        },
    },
    {
        "id": "Q15",
        "message": (
            "After defeating Golem, what should I do next"
            " to progress toward the final boss?"
        ),
        "state": {
            "game_version": "1.4.4.9",
            "gear": {"armor": [], "accessories": [], "weapon": None},
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                    "Plantera",
                    "Golem",
                ],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q03",
        "message": "Why do I keep dying to the Twins?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "hallowed headgear"},
                    {"item_id": 0, "name": "hallowed plate mail"},
                    {"item_id": 0, "name": "hallowed greaves"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "megashark"},
            },
            "world": {
                "hardmode": True,
                "downed_bosses": ["Wall of Flesh"],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q04",
        "message": "What accessories should I use for a Ranger in Hardmode?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "cobalt hat"},
                    {"item_id": 0, "name": "cobalt breastplate"},
                    {"item_id": 0, "name": "cobalt leggings"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "musket"},
            },
            "world": {
                "hardmode": True,
                "downed_bosses": ["Wall of Flesh"],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q05",
        "message": ("What is the optimal setup for a Summoner against Moon Lord?"),
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "tiki mask"},
                    {"item_id": 0, "name": "tiki shirt"},
                    {"item_id": 0, "name": "tiki pants"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "raven staff"},
            },
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                    "Plantera",
                    "Golem",
                    "Lunatic Cultist",
                ],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q06",
        "message": "I've beaten all three mech bosses, what's next?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {"armor": [], "accessories": [], "weapon": None},
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                ],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q07",
        "message": "What buffs should I use before fighting the Wall of Flesh?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "molten helmet"},
                    {"item_id": 0, "name": "molten breastplate"},
                    {"item_id": 0, "name": "molten greaves"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "nights edge"},
            },
            "world": {
                "hardmode": False,
                "downed_bosses": [
                    "Eye of Cthulhu",
                    "Eater of Worlds",
                    "Skeletron",
                ],
                "biome": "underworld",
            },
        },
    },
    {
        "id": "Q08",
        "message": "How do I get a Terra Blade?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {"armor": [], "accessories": [], "weapon": None},
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                ],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q09",
        "message": ("What weapons should a Melee player use after defeating Golem?"),
        "state": {
            "game_version": "1.4.4.9",
            "gear": {
                "armor": [
                    {"item_id": 0, "name": "chlorophyte mask"},
                    {"item_id": 0, "name": "hallowed plate mail"},
                    {"item_id": 0, "name": "hallowed greaves"},
                ],
                "accessories": [],
                "weapon": {"item_id": 0, "name": "terra blade"},
            },
            "world": {
                "hardmode": True,
                "downed_bosses": [
                    "Wall of Flesh",
                    "The Destroyer",
                    "The Twins",
                    "Skeletron Prime",
                    "Plantera",
                    "Golem",
                ],
                "biome": "forest",
            },
        },
    },
    {
        "id": "Q10",
        "message": "What is the best pre-boss armor for a new character?",
        "state": {
            "game_version": "1.4.4.9",
            "gear": {"armor": [], "accessories": [], "weapon": None},
            "world": {
                "hardmode": False,
                "downed_bosses": [],
                "biome": "forest",
            },
        },
    },
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def post_ask(
    client: httpx.Client,
    base_url: str,
    question: dict[str, Any],
) -> dict[str, Any]:
    """POST /bot/ask for one question; return a result dict."""
    payload = {"message": question["message"], "state": question["state"]}
    t0 = time.monotonic()
    try:
        resp = client.post(f"{base_url}/bot/ask", json=payload, timeout=120.0)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        return {
            "id": question["id"],
            "message": question["message"],
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "routing": body.get("routing") if isinstance(body, dict) else None,
            "answer": body.get("answer") if isinstance(body, dict) else None,
            "source_chunks_count": (
                len(body.get("source_chunks", [])) if isinstance(body, dict) else None
            ),
            "response_body": body,
            "input_tokens": None,  # filled manually from Langfuse
            "output_tokens": None,  # filled manually from Langfuse
            "cost_usd": None,  # computed below when tokens are present
        }
    except httpx.RequestError as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {
            "id": question["id"],
            "message": question["message"],
            "status_code": None,
            "latency_ms": latency_ms,
            "routing": None,
            "answer": None,
            "source_chunks_count": None,
            "response_body": {"error": str(exc)},
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        }


def _fmt(value: Any, width: int = 10) -> str:
    s = "PENDING" if value is None else str(value)
    return s[:width].ljust(width)


def print_summary(results: list[dict[str, Any]]) -> None:
    header = (
        f"{'ID':<6} {'Status':<7} {'Routing':<8} {'Chunks':<7}"
        f" {'Latency ms':<11} {'In tok':<8} {'Out tok':<8} {'Cost USD':<10}"
    )
    print()
    print(header)
    print("-" * len(header))
    for r in results:
        cost = (
            f"{compute_cost(r['input_tokens'], r['output_tokens']):.5f}"
            if r["input_tokens"] is not None and r["output_tokens"] is not None
            else "PENDING"
        )
        print(
            f"{_fmt(r['id'], 6)}"
            f" {_fmt(r['status_code'], 7)}"
            f" {_fmt(r['routing'], 8)}"
            f" {_fmt(r['source_chunks_count'], 7)}"
            f" {_fmt(r['latency_ms'], 11)}"
            f" {_fmt(r['input_tokens'], 8)}"
            f" {_fmt(r['output_tokens'], 8)}"
            f" {cost:<10}"
        )
    print()


# ── Main ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the running backend (default: http://localhost:8000)",
    )
    p.add_argument(
        "--output",
        default=None,
        help=(
            "Path to write JSON output "
            "(default: measurements/agent_cost_<timestamp>.json)"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(
        args.output
        or Path(__file__).parent.parent
        / "measurements"
        / f"agent_cost_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Measuring {len(QUESTIONS)} questions against {args.url} …")

    results: list[dict[str, Any]] = []
    with httpx.Client() as client:
        for i, question in enumerate(QUESTIONS, 1):
            msg_preview = question["message"][:60]
            print(f"  [{i:02d}/{len(QUESTIONS)}] {question['id']}: {msg_preview}…")
            result = post_ask(client, args.url, question)
            results.append(result)

    output_path.write_text(
        json.dumps(
            {"url": args.url, "timestamp": timestamp, "results": results}, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\nResults written to: {output_path}")

    print_summary(results)

    failed = [r for r in results if r["status_code"] != 200]
    if failed:
        print(f"WARNING: {len(failed)} request(s) did not return 200.")
        sys.exit(1)


if __name__ == "__main__":
    main()
