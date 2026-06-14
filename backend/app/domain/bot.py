from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ItemRef(BaseModel):
    item_id: int = 0  # Terraria internal ID (matches Cargo Items.itemid)
    name: str = ""  # human-readable; localization-dependent, not canonical
    prefix: str | None = None  # modifier, e.g. "Legendary" / "Unreal"
    stack: int = 1


class GearState(BaseModel):
    armor: list[ItemRef] = Field(default_factory=list)
    accessories: list[ItemRef] = Field(default_factory=list)
    weapon: ItemRef | None = None


class PlayerStats(BaseModel):
    life: int = 100
    max_life: int = 100
    mana: int = 20
    max_mana: int = 20
    defense: int = 0


class WorldState(BaseModel):
    hardmode: bool = False
    downed_bosses: list[str] = Field(default_factory=list)
    biome: str = "forest"


class StatePayload(BaseModel):
    game_version: str = "1.4.4.9"
    gear: GearState = Field(default_factory=GearState)
    inventory: list[ItemRef] = Field(default_factory=list)
    stats: PlayerStats = Field(default_factory=PlayerStats)
    world: WorldState = Field(default_factory=WorldState)


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
