"""RAG eval harness — measures hit@k and MRR@10 against the golden set.

Usage (two modes):

    # pytest (deselected from default ci.yml run; needs live DB):
    pytest -m eval --tb=short

    # standalone (for local debugging without pytest overhead):
    DATABASE_URL=postgresql+asyncpg://... uv run python -m app.eval.rag.harness

Both modes exit non-zero on threshold-assertion failure.

Golden set: backend/data/eval/eval_rag.jsonl (committed; tracked as source of
truth).  EVALS.md §1.1 originally listed a different path — updated in this PR.

Threshold logic:
    - If eval_thresholds.yaml has PENDING values  → print measurements, exit 0.
    - If thresholds are set                        → assert >= threshold, exit 1
      on any failure.  The CI workflow (eval-rag.yml) relies on this exit code.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import make_session_factory
from app.rag.embedder import Embedder
from app.rag.pipeline import RetrievalPipeline

# ── Paths ─────────────────────────────────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).parent.parent.parent.parent  # backend/
_GOLDEN_SET = _BACKEND_ROOT / "data" / "eval" / "eval_rag.jsonl"
_THRESHOLDS = _BACKEND_ROOT.parent / "eval_thresholds.yaml"


# ── Metrics ───────────────────────────────────────────────────────────────────


def _hit_at_k(retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> bool:
    """True if any ground-truth ID appears in the first k retrieved IDs."""
    top_k = set(retrieved_ids[:k])
    return bool(top_k.intersection(ground_truth_ids))


def _reciprocal_rank(retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
    """1/rank of the first ground-truth hit in retrieved_ids, or 0.0."""
    truth = set(ground_truth_ids)
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in truth:
            return 1.0 / rank
    return 0.0


# ── Harness ───────────────────────────────────────────────────────────────────


async def run_harness(output_path: Path | None = None) -> dict[str, Any]:
    """Run all golden-set questions and return the full report dict."""
    if not _GOLDEN_SET.exists():
        sys.exit(f"ERROR: golden set not found at {_GOLDEN_SET}")

    questions = [
        json.loads(line) for line in _GOLDEN_SET.read_text().splitlines() if line
    ]

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("ERROR: DATABASE_URL env var is required")

    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_factory = make_session_factory(engine)
    embedder = Embedder()
    pipeline = RetrievalPipeline(session_factory=session_factory, embedder=embedder)

    per_question: list[dict[str, Any]] = []
    latencies_ms: list[float] = []

    for q in questions:
        question: str = q["question"]
        game_version: str = q["game_version"]
        ground_truth: list[str] = q["ground_truth_chunks"]

        t0 = time.monotonic()
        chunks = await pipeline.retrieve(question, game_version=game_version, k=10)
        latency_ms = (time.monotonic() - t0) * 1000
        latencies_ms.append(latency_ms)

        retrieved_ids = [str(c.id) for c in chunks]

        per_question.append(
            {
                "question": question,
                "game_version": game_version,
                "hit_at_1": _hit_at_k(retrieved_ids, ground_truth, 1),
                "hit_at_3": _hit_at_k(retrieved_ids, ground_truth, 3),
                "hit_at_5": _hit_at_k(retrieved_ids, ground_truth, 5),
                "hit_at_10": _hit_at_k(retrieved_ids, ground_truth, 10),
                "reciprocal_rank": _reciprocal_rank(retrieved_ids, ground_truth),
                "top5_chunks": [
                    {
                        "id": str(c.id),
                        "page_title": c.page_title,
                        "section": c.section,
                        "score": round(c.score, 4),
                    }
                    for c in chunks[:5]
                ],
                "ground_truth_chunks": ground_truth,
                "latency_ms": round(latency_ms, 1),
            }
        )

    await engine.dispose()

    n = len(per_question)
    agg: dict[str, Any] = {
        "hit_at_1": sum(q["hit_at_1"] for q in per_question) / n,
        "hit_at_3": sum(q["hit_at_3"] for q in per_question) / n,
        "hit_at_5": sum(q["hit_at_5"] for q in per_question) / n,
        "hit_at_10": sum(q["hit_at_10"] for q in per_question) / n,
        "mrr_at_10": sum(q["reciprocal_rank"] for q in per_question) / n,
        "median_latency_ms": round(statistics.median(latencies_ms), 1),
        "p95_latency_ms": round(sorted(latencies_ms)[int(len(latencies_ms) * 0.95)], 1),
    }

    report: dict[str, Any] = {"aggregate": agg, "per_question": per_question}

    if output_path is not None:
        output_path.write_text(json.dumps(report, indent=2))

    return report


def _print_report(report: dict[str, Any]) -> None:
    agg = report["aggregate"]
    print("\n── Aggregate ────────────────────────────────────────────────")
    print(f"  hit@1   : {agg['hit_at_1']:.3f}")
    print(f"  hit@3   : {agg['hit_at_3']:.3f}")
    print(f"  hit@5   : {agg['hit_at_5']:.3f}  ← primary gate")
    print(f"  hit@10  : {agg['hit_at_10']:.3f}")
    print(f"  MRR@10  : {agg['mrr_at_10']:.3f}")
    print(
        f"  latency : {agg['median_latency_ms']} ms median"
        f"  /  {agg['p95_latency_ms']} ms p95"
    )
    print("\n── Per question ─────────────────────────────────────────────")
    for i, q in enumerate(report["per_question"], start=1):
        h1 = "✓" if q["hit_at_1"] else "·"
        h3 = "✓" if q["hit_at_3"] else "·"
        h5 = "✓" if q["hit_at_5"] else "·"
        h10 = "✓" if q["hit_at_10"] else "·"
        rr = q["reciprocal_rank"]
        lat = q["latency_ms"]
        print(
            f"  Q{i:02d} @1={h1} @3={h3} @5={h5} @10={h10}"
            f"  RR={rr:.3f}  {lat:.0f}ms  {q['question'][:60]}"
        )
    print()


def _assert_thresholds(report: dict[str, Any]) -> None:
    """Check aggregate metrics against eval_thresholds.yaml.

    Skips individual checks when the threshold value is 'PENDING'.
    Raises AssertionError (exits 1 via pytest) or sys.exit(1) (standalone)
    if any committed threshold is violated.
    """
    if not _THRESHOLDS.exists():
        print(f"WARNING: eval_thresholds.yaml not found at {_THRESHOLDS}; skipping.")
        return

    thresholds = yaml.safe_load(_THRESHOLDS.read_text())
    rag_t = thresholds.get("rag", {})
    agg = report["aggregate"]
    failures: list[str] = []

    def _check(key: str, measured: float, threshold_key: str) -> None:
        threshold = rag_t.get(threshold_key)
        if threshold is None or threshold == "PENDING":
            print(f"  {threshold_key}: PENDING (measured={measured:.3f})")
            return
        if measured < float(threshold):
            failures.append(
                f"{threshold_key}: measured {measured:.3f} < threshold {threshold}"
            )
        else:
            print(f"  {threshold_key}: {measured:.3f} >= {threshold} ✓")

    print("── Threshold checks ─────────────────────────────────────────")
    _check("hit_at_1", agg["hit_at_1"], "hit_at_1_min")
    _check("hit_at_5", agg["hit_at_5"], "hit_at_k_min")
    _check("mrr_at_10", agg["mrr_at_10"], "mrr_at_10_min")
    _check("p95_latency", agg["p95_latency_ms"], "p95_latency_ms_max")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
        raise AssertionError(
            f"{len(failures)} threshold(s) violated: {'; '.join(failures)}"
        )


# ── pytest entry point ────────────────────────────────────────────────────────


@pytest.mark.eval
def test_rag_retrieval_thresholds() -> None:
    """Measure hit@k + MRR@10 + latency on the 15-question golden set.

    Requires a live DB with the 1.4.4.9 corpus loaded (DATABASE_URL env var).
    Deselected from default CI by addopts = ["-m", "not eval and not redteam"].
    Run via: pytest -m eval  or  eval-rag.yml workflow_dispatch.
    """
    report = asyncio.run(run_harness(output_path=Path("eval_report.json")))
    _print_report(report)
    _assert_thresholds(report)

    # Suspicious-high guard: hit@5 >= 0.85 warrants golden-set investigation.
    hit5 = report["aggregate"]["hit_at_5"]
    if hit5 >= 0.85:
        print(
            f"\nWARNING: hit@5={hit5:.3f} >= 0.85 — investigate the golden set "
            "before committing thresholds. Verify Q9 (Megashark vs Uzi) and "
            "Q15 (post-Golem progression) are genuinely hard."
        )


# ── standalone entry point ────────────────────────────────────────────────────


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="RAG eval harness")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON report")
    args = parser.parse_args()

    report = await run_harness(output_path=args.output)
    _print_report(report)

    hit5 = report["aggregate"]["hit_at_5"]
    if hit5 >= 0.85:
        print(
            f"WARNING: hit@5={hit5:.3f} >= 0.85 — investigate before committing "
            "thresholds. See plan §D suspicious-high guard."
        )

    try:
        _assert_thresholds(report)
    except AssertionError as exc:
        sys.exit(f"THRESHOLD FAILURE: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
