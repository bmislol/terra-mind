from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoadedPrompts:
    router: str
    faq_answer: str
    agent_system: str
