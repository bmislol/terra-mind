"""Unit tests for app/agent/tools.py.

query_wiki: mocked RetrievalPipeline — verifies return shape.
analyze_loadout: hardcoded item-dict class detection, 6+ gear fixtures.
suggest_next_boss: deterministic decision tree, 8+ progression fixtures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.agent.tools import analyze_loadout, query_wiki, suggest_next_boss
from app.domain.bot import GearState, ItemRef, StatePayload, WorldState
from app.rag.models import RetrievedChunk

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_chunk(title: str = "Iron Sword", section: str = "stats") -> RetrievedChunk:
    return RetrievedChunk(
        id=uuid4(),
        page_id=1,
        page_title=title,
        section=section,
        content=f"Content about {title}.",
        source_url=f"https://terraria.wiki.gg/wiki/{title.replace(' ', '_')}",
        game_version="1.4.4.9",
        score=0.85,
    )


def _gear(*names: str) -> GearState:
    """Build a GearState with the named items as armor slots."""
    return GearState(armor=[ItemRef(name=n) for n in names])


def _weapon(name: str) -> GearState:
    return GearState(weapon=ItemRef(name=name))


def _world(*, hardmode: bool = False, downed: list[str] | None = None) -> WorldState:
    return WorldState(hardmode=hardmode, downed_bosses=downed or [])


# ── query_wiki ────────────────────────────────────────────────────────────────


async def test_query_wiki_returns_dicts_with_required_keys() -> None:
    mock_retrieval = MagicMock()
    chunk = _make_chunk("Megashark", "stats")
    mock_retrieval.retrieve = AsyncMock(return_value=[chunk])

    results = await query_wiki(
        "Megashark damage",
        game_version="1.4.4.9",
        k=3,
        retrieval=mock_retrieval,
    )

    assert len(results) == 1
    r = results[0]
    assert r["page_title"] == "Megashark"
    assert r["section"] == "stats"
    assert r["content"] == "Content about Megashark."
    assert r["source_url"] == "https://terraria.wiki.gg/wiki/Megashark"
    assert isinstance(r["score"], float)


async def test_query_wiki_passes_game_version_and_k_to_pipeline() -> None:
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve = AsyncMock(return_value=[])

    await query_wiki(
        "boss drops",
        game_version="1.4.4.9",
        k=7,
        retrieval=mock_retrieval,
    )

    mock_retrieval.retrieve.assert_awaited_once_with(
        "boss drops",
        game_version="1.4.4.9",
        k=7,
        parent_observation=None,
    )


async def test_query_wiki_empty_corpus_returns_empty_list() -> None:
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve = AsyncMock(return_value=[])

    results = await query_wiki(
        "obscure query", game_version="1.4.4.9", k=5, retrieval=mock_retrieval
    )

    assert results == []


# ── analyze_loadout ───────────────────────────────────────────────────────────


def test_analyze_loadout_melee_armor_detected() -> None:
    sp = StatePayload(
        gear=_gear("molten helmet", "molten breastplate", "molten greaves"),
    )
    result = analyze_loadout(sp)
    assert result["class"] == "melee"
    assert result["confidence"] == "high"
    assert result["needs_llm_fallback"] is False


def test_analyze_loadout_ranger_weapon_detected() -> None:
    sp = StatePayload(gear=_weapon("megashark"))
    result = analyze_loadout(sp)
    assert result["class"] == "ranger"


def test_analyze_loadout_mage_armor_detected() -> None:
    sp = StatePayload(
        gear=_gear("meteor helmet", "meteor suit", "meteor leggings"),
    )
    result = analyze_loadout(sp)
    assert result["class"] == "mage"
    assert result["confidence"] == "high"


def test_analyze_loadout_summoner_detected() -> None:
    sp = StatePayload(
        gear=_gear("bee helmet", "bee breastplate", "bee greaves"),
    )
    result = analyze_loadout(sp)
    assert result["class"] == "summoner"


def test_analyze_loadout_empty_gear_returns_no_class() -> None:
    sp = StatePayload()
    result = analyze_loadout(sp)
    assert result["class"] is None
    assert result["confidence"] == "low"
    assert result["needs_llm_fallback"] is True


def test_analyze_loadout_unknown_items_fallback() -> None:
    sp = StatePayload(gear=_gear("wooden hammer", "gold crown"))
    result = analyze_loadout(sp)
    assert result["class"] is None
    assert result["needs_llm_fallback"] is True


def test_analyze_loadout_progression_stage_pre_boss() -> None:
    sp = StatePayload()
    result = analyze_loadout(sp)
    assert result["progression_stage"] == "pre-boss"


def test_analyze_loadout_progression_stage_early_hardmode() -> None:
    sp = StatePayload(world=_world(hardmode=True, downed=["Wall of Flesh"]))
    result = analyze_loadout(sp)
    assert result["progression_stage"] == "early-hardmode"


# ── suggest_next_boss ─────────────────────────────────────────────────────────


def test_suggest_next_boss_fresh_world() -> None:
    sp = StatePayload()
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Eye of Cthulhu"


def test_suggest_next_boss_after_eye_of_cthulhu() -> None:
    sp = StatePayload(world=_world(downed=["Eye of Cthulhu"]))
    result = suggest_next_boss(sp)
    nb = result["next_boss"]
    assert "Eater of Worlds" in nb or "Brain of Cthulhu" in nb


def test_suggest_next_boss_after_eow() -> None:
    sp = StatePayload(world=_world(downed=["Eye of Cthulhu", "Eater of Worlds"]))
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Skeletron"


def test_suggest_next_boss_after_skeletron() -> None:
    sp = StatePayload(
        world=_world(downed=["Eye of Cthulhu", "Eater of Worlds", "Skeletron"])
    )
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Wall of Flesh"


def test_suggest_next_boss_early_hardmode_needs_mech() -> None:
    sp = StatePayload(world=_world(hardmode=True, downed=["Wall of Flesh"]))
    result = suggest_next_boss(sp)
    assert "Mechanical" in result["next_boss"] or "Destroyer" in result["next_boss"]


def test_suggest_next_boss_after_all_mech() -> None:
    sp = StatePayload(
        world=_world(
            hardmode=True,
            downed=["The Destroyer", "The Twins", "Skeletron Prime"],
        )
    )
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Plantera"


def test_suggest_next_boss_after_plantera() -> None:
    sp = StatePayload(
        world=_world(
            hardmode=True,
            downed=["The Destroyer", "The Twins", "Skeletron Prime", "Plantera"],
        )
    )
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Golem"


def test_suggest_next_boss_after_golem() -> None:
    sp = StatePayload(
        world=_world(
            hardmode=True,
            downed=[
                "The Destroyer",
                "The Twins",
                "Skeletron Prime",
                "Plantera",
                "Golem",
            ],
        )
    )
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Lunatic Cultist"


def test_suggest_next_boss_endgame() -> None:
    sp = StatePayload(
        world=_world(
            hardmode=True,
            downed=[
                "The Destroyer",
                "The Twins",
                "Skeletron Prime",
                "Plantera",
                "Golem",
                "Lunatic Cultist",
            ],
        )
    )
    result = suggest_next_boss(sp)
    assert result["next_boss"] == "Moon Lord"
