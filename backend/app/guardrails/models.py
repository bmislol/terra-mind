"""Guardrail domain types (Phase 6.1, D-034).

A ``Verdict`` is the result of a guardrail check on one message (input) or reply
(output). The player only ever sees the generic ``REFUSAL_MESSAGE`` — the
``category``/``reason`` are for the audit log + tracing, never returned to the
caller (no information leak to someone probing the filter).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    """Threat categories the guardrail blocks (D-034)."""

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"  # game/progression cheat & dev-item requests
    TOXICITY = "toxicity"


@dataclass(frozen=True)
class Verdict:
    """Outcome of a guardrail check.

    ``blocked`` drives the control flow; ``category``/``reason`` are diagnostic
    (audit + logs), not shown to the player.
    """

    blocked: bool
    category: Category | None = None
    reason: str = ""

    @classmethod
    def allow(cls) -> Verdict:
        return cls(blocked=False)

    @classmethod
    def block(cls, category: Category, reason: str) -> Verdict:
        return cls(blocked=True, category=category, reason=reason)


#: Player-facing refusal. Generic on purpose — it does not reveal which rule or
#: category fired, so an attacker can't probe the filter by reading the reply.
REFUSAL_MESSAGE = (
    "I can't help with that. I'm your Terraria survival companion — ask me "
    "about your gear, bosses, crafting, or what to do next."
)
