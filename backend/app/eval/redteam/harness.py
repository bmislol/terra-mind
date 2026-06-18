"""Red-team eval harness (Phase 6.1, D-034) — the graded safety gate.

Runs the red-team set (``data/eval/redteam.jsonl``) through the FULL guardrail
(``check_input`` / ``check_output`` — Tier 1 + the REAL Tier-2 judge) and reports:

  - **successful injections** = ``must_block`` records that PASSED — the gate
    (``<= redteam.max_successful_injections``, which is 0);
  - **over-blocks** = benign controls (``must_block: false``) that were BLOCKED —
    must be 0 (precision / no-over-block guard).

Real LLM calls (the judge) → needs ``ANTHROPIC_API_KEY``. Runs in
``eval-redteam.yml`` (PR-triggered) and via
``pytest tests/test_eval_redteam.py -m redteam``, **not** the default ``pytest``
(deselected by the marker). The gate compares ``successful <= max`` **directly**:
that key has no ``_min``/``_max`` suffix, so ``passes_threshold`` would raise on
it (D-022 / D-034).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from app.guardrails.judge import check_input, check_output
from app.guardrails.models import Verdict
from app.infra.anthropic import AnthropicClient

_BACKEND_ROOT = Path(__file__).parents[3]  # backend/
_REDTEAM_SET = _BACKEND_ROOT / "data" / "eval" / "redteam.jsonl"
_JUDGE_PROMPT = _BACKEND_ROOT / "app" / "prompts" / "guardrail_judge.md"
_THRESHOLDS = _BACKEND_ROOT.parent / "eval_thresholds.yaml"

_MAX_CONCURRENCY = 5  # bound the real LLM calls


async def _evaluate(
    record: dict[str, Any], *, anthropic: AnthropicClient, judge_prompt: str
) -> Verdict:
    if record["surface"] == "input":
        return await check_input(
            record["text"], anthropic=anthropic, judge_prompt=judge_prompt
        )
    return await check_output(
        record["text"], anthropic=anthropic, judge_prompt=judge_prompt
    )


async def run_harness() -> dict[str, Any]:
    """Evaluate every red-team record and return the report dict."""
    if not _REDTEAM_SET.exists():
        sys.exit(f"ERROR: red-team set not found at {_REDTEAM_SET}")
    records = [
        json.loads(line)
        for line in _REDTEAM_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY is required for the red-team harness")
    anthropic = AnthropicClient(api_key=api_key)
    judge_prompt = _JUDGE_PROMPT.read_text(encoding="utf-8")

    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _one(record: dict[str, Any]) -> tuple[dict[str, Any], Verdict]:
        async with sem:
            return record, await _evaluate(
                record, anthropic=anthropic, judge_prompt=judge_prompt
            )

    evaluated = await asyncio.gather(*(_one(r) for r in records))

    successful: list[dict[str, Any]] = []
    over_blocks: list[dict[str, Any]] = []
    per_record: list[dict[str, Any]] = []
    for record, verdict in evaluated:
        must_block = bool(record["must_block"])
        if must_block and not verdict.blocked:
            successful.append(record)
        if not must_block and verdict.blocked:
            over_blocks.append({**record, "blocked_as": str(verdict.category)})
        per_record.append(
            {
                "text": record["text"][:72],
                "category": record["category"],
                "surface": record["surface"],
                "must_block": must_block,
                "blocked": verdict.blocked,
                "ok": verdict.blocked == must_block,
                "reason": verdict.reason,
            }
        )

    thresholds = yaml.safe_load(_THRESHOLDS.read_text(encoding="utf-8"))
    max_successful = int(thresholds["redteam"]["max_successful_injections"])
    return {
        "n": len(records),
        "successful": successful,
        "over_blocks": over_blocks,
        "max_successful": max_successful,
        "per_record": per_record,
    }


def print_report(report: dict[str, Any]) -> None:
    print("\n── Red-team results ─────────────────────────────────────────")
    for r in report["per_record"]:
        mark = "✓" if r["ok"] else "✗"
        want = "BLOCK" if r["must_block"] else "ALLOW"
        got = "BLOCK" if r["blocked"] else "ALLOW"
        print(
            f"  {mark} [{r['surface'][:3]}/{r['category'][:12]:12}] "
            f"want={want} got={got} ({r['reason'] or '-'})  {r['text']}"
        )
    print(
        f"\n  records={report['n']}  "
        f"successful_injections={len(report['successful'])} "
        f"(max {report['max_successful']})  "
        f"over_blocks={len(report['over_blocks'])}"
    )
    if report["successful"]:
        print("\n  SLIPPED (must_block passed):")
        for r in report["successful"]:
            print(f"    ✗ [{r['category']}/{r['surface']}] {r['text']}")
    if report["over_blocks"]:
        print("\n  OVER-BLOCKED (benign blocked):")
        for r in report["over_blocks"]:
            print(f"    ✗ [{r['blocked_as']}] {r['text']}")
    print()


async def _main() -> None:
    report = await run_harness()
    print_report(report)
    if len(report["successful"]) > report["max_successful"]:
        sys.exit(f"FAIL: {len(report['successful'])} successful injection(s)")
    if report["over_blocks"]:
        sys.exit(f"FAIL: {len(report['over_blocks'])} over-block(s)")
    print("PASS: 0 successful injections, 0 over-blocks.")


if __name__ == "__main__":
    asyncio.run(_main())
