"""Threshold direction helpers for eval_thresholds.yaml keys.

Convention (D-022):
  - Keys ending with ``_min`` are lower-bound floors:  measured >= threshold passes.
  - Keys ending with ``_max`` are upper-bound ceilings: measured <= threshold passes.
  - Any other suffix raises ValueError immediately so a future contributor who adds
    a new threshold key with the wrong suffix gets a loud error rather than silent
    misbehaviour.
"""

from __future__ import annotations


def passes_threshold(key: str, measured: float, threshold: float) -> bool:
    """Return True if measured satisfies the threshold for key.

    Raises ValueError for keys with neither ``_min`` nor ``_max`` suffix.
    """
    if key.endswith("_min"):
        return measured >= threshold
    if key.endswith("_max"):
        return measured <= threshold
    raise ValueError(
        f"Unknown threshold key suffix in {key!r}: expected '_min' (floor) or "
        "'_max' (ceiling). Rename the key or handle it explicitly."
    )


def zero_is_valid_for_key(key: str) -> bool:
    """Return True if 0 is a meaningful threshold value for key.

    _min and _max keys treat 0 as "no gate" — the API refuses to boot.
    Other keys (e.g. redteam.max_successful_injections) treat 0 as a valid
    strict floor.
    """
    if key.endswith("_min") or key.endswith("_max"):
        return False
    return True
