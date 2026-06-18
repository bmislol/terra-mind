from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoadedPrompts:
    router: str
    faq_answer: str
    agent_system: str
    class_fallback: str
    # Tier-2 guardrail judge (Phase 6.1, D-034). Defaulted so the many test
    # constructors that don't exercise the judge stay untouched; the lifespan
    # always loads the real file (refuse-to-boot if missing, like the others).
    guardrail_judge: str = ""
