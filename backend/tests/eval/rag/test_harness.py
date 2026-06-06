"""Unit tests for harness threshold direction logic.

Tests cover app.core.threshold_directions directly (the shared helper used
by both the harness and the refuse-to-boot check) plus an integration test
on _assert_thresholds itself to confirm the harness delegates correctly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from app.core.threshold_directions import passes_threshold

# ── passes_threshold — _min (floor) ──────────────────────────────────────────


def test_min_key_at_threshold_passes() -> None:
    assert passes_threshold("hit_at_k_min", 0.55, 0.55) is True


def test_min_key_above_threshold_passes() -> None:
    assert passes_threshold("hit_at_k_min", 0.667, 0.55) is True


def test_min_key_below_threshold_fails() -> None:
    assert passes_threshold("hit_at_k_min", 0.54, 0.55) is False


# ── passes_threshold — _max (ceiling) ────────────────────────────────────────


def test_max_key_at_threshold_passes() -> None:
    assert passes_threshold("p95_latency_ms_max", 300.0, 300.0) is True


def test_max_key_below_threshold_passes() -> None:
    # 164 ms measured against a 300 ms ceiling: this is the live-harness
    # case that was silently failing before the direction fix.
    assert passes_threshold("p95_latency_ms_max", 164.2, 300.0) is True


def test_max_key_above_threshold_fails() -> None:
    assert passes_threshold("p95_latency_ms_max", 301.0, 300.0) is False


# ── passes_threshold — unknown suffix raises ──────────────────────────────────


def test_unknown_suffix_raises_value_error() -> None:
    with pytest.raises(ValueError, match="_min.*_max"):
        passes_threshold("some_value", 1.0, 1.0)


# ── _assert_thresholds integration ───────────────────────────────────────────


def _report(p95_ms: float = 164.2, hit5: float = 0.667) -> dict[str, Any]:
    return {
        "aggregate": {
            "hit_at_1": 0.467,
            "hit_at_3": 0.600,
            "hit_at_5": hit5,
            "hit_at_10": 0.867,
            "mrr_at_10": 0.576,
            "median_latency_ms": 5.5,
            "p95_latency_ms": p95_ms,
        },
        "per_question": [],
    }


def test_assert_thresholds_max_key_passes_below_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """164 ms measured against a 300 ms ceiling must pass, not fail."""
    import app.eval.rag.harness as harness_mod

    tf = tmp_path / "thresholds.yaml"
    tf.write_text(
        textwrap.dedent("""\
        rag:
          hit_at_k_min: 0.55
          p95_latency_ms_max: 300
    """)
    )
    monkeypatch.setattr(harness_mod, "_THRESHOLDS", tf)
    harness_mod._assert_thresholds(_report(p95_ms=164.2))  # must not raise


def test_assert_thresholds_max_key_fails_above_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """301 ms measured against a 300 ms ceiling must fail."""
    import app.eval.rag.harness as harness_mod

    tf = tmp_path / "thresholds.yaml"
    tf.write_text("rag:\n  p95_latency_ms_max: 300\n")
    monkeypatch.setattr(harness_mod, "_THRESHOLDS", tf)
    with pytest.raises(AssertionError, match="p95_latency_ms_max"):
        harness_mod._assert_thresholds(_report(p95_ms=301.0))


def test_assert_thresholds_min_key_passes_above_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.eval.rag.harness as harness_mod

    tf = tmp_path / "thresholds.yaml"
    tf.write_text("rag:\n  hit_at_k_min: 0.55\n")
    monkeypatch.setattr(harness_mod, "_THRESHOLDS", tf)
    harness_mod._assert_thresholds(_report(hit5=0.667))  # must not raise


def test_assert_thresholds_min_key_fails_below_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.eval.rag.harness as harness_mod

    tf = tmp_path / "thresholds.yaml"
    tf.write_text("rag:\n  hit_at_k_min: 0.55\n")
    monkeypatch.setattr(harness_mod, "_THRESHOLDS", tf)
    with pytest.raises(AssertionError, match="hit_at_k_min"):
        harness_mod._assert_thresholds(_report(hit5=0.40))
