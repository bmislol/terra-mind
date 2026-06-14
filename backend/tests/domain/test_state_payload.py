"""Schema tests for StatePayload (Phase 3.3 commit 2 — schema finalization).

Verifies the expanded schema (prefix/stack on ItemRef, inventory + stats on
StatePayload) plus backward-compat with Phase-3.2-shaped payloads.
"""

from __future__ import annotations

from app.domain.bot import GearState, ItemRef, PlayerStats, StatePayload, WorldState


def test_default_state_payload_constructs_with_safe_defaults() -> None:
    sp = StatePayload()
    assert sp.game_version == "1.4.4.9"
    assert sp.gear.armor == []
    assert sp.gear.accessories == []
    assert sp.gear.weapon is None
    assert sp.inventory == []
    assert isinstance(sp.stats, PlayerStats)
    assert sp.stats.life == 100
    assert sp.stats.max_life == 100
    assert sp.stats.mana == 20
    assert sp.stats.max_mana == 20
    assert sp.stats.defense == 0
    assert sp.world.hardmode is False
    assert sp.world.downed_bosses == []
    assert sp.world.biome == "forest"


def test_item_ref_defaults_and_prefix_stack() -> None:
    bare = ItemRef()
    assert bare.item_id == 0
    assert bare.name == ""
    assert bare.prefix is None
    assert bare.stack == 1

    full = ItemRef(item_id=3389, name="Megashark", prefix="Unreal", stack=1)
    assert full.item_id == 3389
    assert full.prefix == "Unreal"
    assert full.stack == 1


def test_full_payload_round_trips_through_dump_and_validate() -> None:
    """The mod sends JSON; a realistic full payload must round-trip."""
    sp = StatePayload(
        game_version="1.4.4.9",
        gear=GearState(
            armor=[
                ItemRef(item_id=1281, name="Fossil Helmet"),
                ItemRef(item_id=1282, name="Fossil Plate"),
                ItemRef(item_id=1283, name="Fossil Greaves"),
            ],
            accessories=[ItemRef(item_id=3223, name="Hermes Boots", prefix="Quick")],
            weapon=ItemRef(item_id=98, name="Megashark", prefix="Unreal"),
        ),
        inventory=[
            ItemRef(item_id=40, name="Wooden Arrow", stack=999),
            ItemRef(item_id=188, name="Lesser Healing Potion", stack=20),
        ],
        stats=PlayerStats(life=300, max_life=400, mana=40, max_mana=60, defense=18),
        world=WorldState(
            hardmode=False,
            downed_bosses=["Eye of Cthulhu", "Eater of Worlds"],
            biome="forest",
        ),
    )

    dumped = sp.model_dump()
    restored = StatePayload.model_validate(dumped)
    assert restored == sp
    # Spot-check nested fields survived the round-trip.
    assert restored.gear.weapon is not None
    assert restored.gear.weapon.prefix == "Unreal"
    assert restored.gear.accessories[0].prefix == "Quick"
    assert restored.inventory[1].stack == 20
    assert restored.stats.defense == 18


def test_backward_compat_phase_3_2_shaped_payload() -> None:
    """A Phase 3.2 payload (gear + world only, no inventory/stats/prefix/stack)
    still validates — new fields fill in via defaults."""
    legacy = {
        "game_version": "1.4.4.9",
        "gear": {
            "armor": [{"item_id": 0, "name": "molten helmet"}],
            "accessories": [],
            "weapon": {"item_id": 0, "name": "megashark"},
        },
        "world": {
            "hardmode": False,
            "downed_bosses": ["Eye of Cthulhu"],
            "biome": "forest",
        },
    }
    sp = StatePayload.model_validate(legacy)
    assert sp.inventory == []
    assert sp.stats.life == 100
    assert sp.gear.armor[0].prefix is None
    assert sp.gear.armor[0].stack == 1
    assert sp.gear.weapon is not None
    assert sp.gear.weapon.name == "megashark"


def test_minimal_message_only_state_is_default() -> None:
    """body.state=None equivalent: StatePayload() is the default the endpoint uses."""
    sp = StatePayload.model_validate({})
    assert sp == StatePayload()
