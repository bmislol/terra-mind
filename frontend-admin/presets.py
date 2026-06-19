"""Preset StatePayloads for the test chat (Phase 5.2).

Each matches the exact `StatePayload` schema the mod sends (backend/app/domain/
bot.py): game_version + gear{armor,accessories,weapon} + inventory + stats +
world. Three classes × three progression stages so the demo shows the agent's
class + progression awareness in one click each.

All three carry **real Cargo item_ids** → the truthful `item_id` class-detection
path (D-026): Copper Shortsword 3507 = melee, Minishark 98 = ranged, Crystal
Storm 518 = magic.
"""

from __future__ import annotations

from typing import Any

_MELEE_PRE_BOSS: dict[str, Any] = {
    "game_version": "1.4.4.9",
    "gear": {
        "armor": [
            {"item_id": 727, "name": "Wood Helmet", "prefix": None, "stack": 1},
            {"item_id": 728, "name": "Wood Breastplate", "prefix": None, "stack": 1},
            {"item_id": 729, "name": "Wood Greaves", "prefix": None, "stack": 1},
        ],
        "accessories": [
            {"item_id": 54, "name": "Hermes Boots", "prefix": "Quick", "stack": 1},
        ],
        "weapon": {
            "item_id": 3507,
            "name": "Copper Shortsword",
            "prefix": None,
            "stack": 1,
        },
    },
    "inventory": [
        {"item_id": 3509, "name": "Copper Pickaxe", "prefix": None, "stack": 1},
    ],
    "stats": {"life": 100, "max_life": 100, "mana": 20, "max_mana": 20, "defense": 4},
    "world": {"hardmode": False, "downed_bosses": [], "biome": "forest"},
}

_RANGER_POST_EOC: dict[str, Any] = {
    "game_version": "1.4.4.9",
    "gear": {
        "armor": [],
        "accessories": [
            {"item_id": 54, "name": "Hermes Boots", "prefix": "Quick", "stack": 1},
        ],
        "weapon": {"item_id": 98, "name": "Minishark", "prefix": "Unreal", "stack": 1},
    },
    "inventory": [
        {"item_id": 40, "name": "Wooden Arrow", "prefix": None, "stack": 250},
    ],
    "stats": {"life": 200, "max_life": 200, "mana": 20, "max_mana": 20, "defense": 8},
    "world": {
        "hardmode": False,
        "downed_bosses": ["Eye of Cthulhu"],
        "biome": "forest",
    },
}

_MAGE_HARDMODE: dict[str, Any] = {
    "game_version": "1.4.4.9",
    "gear": {
        "armor": [
            {"item_id": 0, "name": "Spectre Mask", "prefix": None, "stack": 1},
            {"item_id": 0, "name": "Spectre Robe", "prefix": None, "stack": 1},
            {"item_id": 0, "name": "Spectre Pants", "prefix": None, "stack": 1},
        ],
        "accessories": [],
        "weapon": {
            "item_id": 518,
            "name": "Crystal Storm",
            "prefix": "Mythical",
            "stack": 1,
        },
    },
    "inventory": [
        {"item_id": 0, "name": "Greater Mana Potion", "prefix": None, "stack": 30},
    ],
    "stats": {
        "life": 400,
        "max_life": 400,
        "mana": 200,
        "max_mana": 200,
        "defense": 30,
    },
    "world": {
        "hardmode": True,
        "downed_bosses": [
            "Wall of Flesh",
            "The Destroyer",
            "The Twins",
            "Skeletron Prime",
            "Plantera",
        ],
        "biome": "underground jungle",
    },
}

# The n≈0 progression baseline: a brand-new world — what the agent says with
# nothing earned yet. Only the starting Copper Shortsword (3507 = melee, the
# truthful item_id path), empty everything else, no bosses, pre-hardmode.
_FRESH_START: dict[str, Any] = {
    "game_version": "1.4.4.9",
    "gear": {
        "armor": [],
        "accessories": [],
        "weapon": {
            "item_id": 3507,
            "name": "Copper Shortsword",
            "prefix": None,
            "stack": 1,
        },
    },
    "inventory": [],
    "stats": {"life": 100, "max_life": 100, "mana": 20, "max_mana": 20, "defense": 0},
    "world": {"hardmode": False, "downed_bosses": [], "biome": "forest"},
}

PRESETS: dict[str, dict[str, Any]] = {
    "Fresh start — brand-new world": _FRESH_START,
    "Melee — pre-boss (early game)": _MELEE_PRE_BOSS,
    "Ranger — post-Eye of Cthulhu": _RANGER_POST_EOC,
    "Mage — hardmode, post-Plantera": _MAGE_HARDMODE,
}
