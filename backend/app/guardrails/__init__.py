"""Guardrails (Phase 6.1, D-034).

Two-tier, deterministic-first input/output filter for ``/bot/ask``. Tier 1 (here,
``rules.py``) is zero-LLM regex; Tier 2 (``judge.py``, commit 2) is a haiku
LLM-judge that escalates only the ambiguous band. The red-team set + harness
(``app/eval/redteam/``) prove ``0 successful injections`` (the graded gate).
"""

from app.guardrails.judge import check_input, check_output, judge
from app.guardrails.models import REFUSAL_MESSAGE, Category, Verdict
from app.guardrails.rules import (
    check_input_deterministic,
    check_output_deterministic,
)

__all__ = [
    "REFUSAL_MESSAGE",
    "Category",
    "Verdict",
    "check_input",
    "check_input_deterministic",
    "check_output",
    "check_output_deterministic",
    "judge",
]
