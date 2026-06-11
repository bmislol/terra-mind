from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class StatePayload(BaseModel):
    game_version: str = "1.4.4.9"


class RoutingDecision(StrEnum):
    faq = "faq"
    agent = "agent"


class ChunkRef(BaseModel):
    page_title: str
    section: str
    source_url: str
    score: float


class BotAnswer(BaseModel):
    answer: str
    source_chunks: list[ChunkRef]
    routing: RoutingDecision
