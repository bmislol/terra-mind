"""Unit tests for scripts/measure_agent_cost.py.  No network calls."""

from __future__ import annotations

from scripts.measure_agent_cost import QUESTIONS, compute_cost


def test_questions_list_has_required_keys() -> None:
    """Every entry must have 'message' and 'state' so /bot/ask accepts it."""
    for q in QUESTIONS:
        assert "message" in q, f"Question {q.get('id')} missing 'message'"
        assert "state" in q, f"Question {q.get('id')} missing 'state'"
        assert isinstance(q["message"], str) and q["message"], (
            f"Question {q.get('id')} has empty message"
        )
        state = q["state"]
        assert "game_version" in state, (
            f"Question {q.get('id')} state missing 'game_version'"
        )
        assert "world" in state, f"Question {q.get('id')} state missing 'world'"
        assert "gear" in state, f"Question {q.get('id')} state missing 'gear'"


def test_questions_list_has_ten_entries() -> None:
    assert len(QUESTIONS) == 10


def test_compute_cost_known_values() -> None:
    """1 000 000 input + 1 000 000 output should cost exactly $4.80."""
    cost = compute_cost(1_000_000, 1_000_000)
    assert abs(cost - 4.80) < 1e-9


def test_compute_cost_zero_tokens() -> None:
    assert compute_cost(0, 0) == 0.0


def test_compute_cost_input_only() -> None:
    """1 000 000 input tokens, 0 output → $0.80."""
    cost = compute_cost(1_000_000, 0)
    assert abs(cost - 0.80) < 1e-9


def test_compute_cost_output_only() -> None:
    """0 input, 1 000 000 output → $4.00."""
    cost = compute_cost(0, 1_000_000)
    assert abs(cost - 4.00) < 1e-9


def test_compute_cost_small_call() -> None:
    """Typical single router call (~300 input, ~50 output) costs under $0.001."""
    cost = compute_cost(300, 50)
    assert cost < 0.001
