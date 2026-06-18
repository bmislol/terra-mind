"""Red-team gate (Phase 6.1, D-034) — the graded safety eval.

Deselected from default CI (``addopts = -m "not eval and not redteam"``); runs in
``eval-redteam.yml`` (PR-triggered, needs ``ANTHROPIC_API_KEY``) and via
``pytest tests/test_eval_redteam.py -m redteam``. A single successful injection
or any over-block turns the build red.
"""

from __future__ import annotations

import asyncio

import pytest

from app.eval.redteam.harness import print_report, run_harness


@pytest.mark.redteam
def test_redteam_zero_successful_and_zero_overblock() -> None:
    report = asyncio.run(run_harness())
    print_report(report)

    # Primary gate — compared DIRECTLY (the key has no _min/_max suffix, so
    # passes_threshold would raise on it; D-022 / D-034).
    n_successful = len(report["successful"])
    assert n_successful <= report["max_successful"], (
        f"{n_successful} successful injection(s) > "
        f"max {report['max_successful']}: {report['successful']}"
    )

    # No-over-block guard — benign controls must never be blocked.
    assert not report["over_blocks"], (
        f"{len(report['over_blocks'])} benign control(s) over-blocked: "
        f"{report['over_blocks']}"
    )
