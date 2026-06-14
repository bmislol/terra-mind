from __future__ import annotations

import json
from typing import Any

from app.agent.class_detection import DEFAULT_CLASSIFIER, ItemClassifier
from app.domain.bot import ItemRef, StatePayload
from app.infra.anthropic import ToolParam
from app.rag.pipeline import RetrievalPipeline

# ── ToolParam schemas exposed to the LLM ─────────────────────────────────────

QUERY_WIKI_TOOL: ToolParam = {
    "name": "query_wiki",
    "description": (
        "Search the Terraria wiki corpus for items, bosses, recipes, "
        "mechanics, and strategies. Returns ranked text excerpts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Specific search query, e.g. 'Megashark damage stats'"
                    " or 'Skeletron boss strategy'."
                ),
            },
            "k": {
                "type": "integer",
                "description": "Maximum number of results (1–10). Default 5.",
            },
        },
        "required": ["query"],
    },
}

ANALYZE_LOADOUT_TOOL: ToolParam = {
    "name": "analyze_loadout",
    "description": (
        "Analyze the player's equipped armor, weapon, and accessories to determine "
        "their class (melee/ranger/mage/summoner) and progression stage. "
        "Call this before giving class-specific gear advice."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

SUGGEST_NEXT_BOSS_TOOL: ToolParam = {
    "name": "suggest_next_boss",
    "description": (
        "Suggest the next boss the player should fight based on their current "
        "world progression (hardmode flag and downed boss list). "
        "Call this when the player asks what to do next or which boss to fight."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

ALL_TOOLS: list[ToolParam] = [
    QUERY_WIKI_TOOL,
    ANALYZE_LOADOUT_TOOL,
    SUGGEST_NEXT_BOSS_TOOL,
]

# Class detection now lives in app/agent/class_detection.py (Cargo-aware,
# D-009). The curated item→class map moved there as CURATED_ITEM_CLASS.
_CLASSES = ("melee", "ranger", "mage", "summoner")


def _normalize(name: str) -> str:
    return name.lower().replace("-", "").replace("'", "").replace(" ", "")


def _progression_stage(state: StatePayload) -> str:
    downed = {_normalize(b) for b in state.world.downed_bosses}
    if state.world.hardmode:
        if "moonlord" in downed:
            return "endgame"
        if "plantera" in downed:
            return "post-plantera"
        mech = {"thedestroyer", "destroyer", "thetwins", "twins", "skeletronprime"}
        if downed & mech:
            return "mid-hardmode"
        return "early-hardmode"
    else:
        if "skeletron" in downed:
            return "mid-pre-hardmode"
        early = {"eyeofcthulhu", "eaterofworlds", "brainofcthulhu"}
        if downed & early:
            return "early-pre-hardmode"
        return "pre-boss"


# ── Tool implementations ──────────────────────────────────────────────────────


async def query_wiki(
    query: str,
    *,
    game_version: str,
    k: int = 5,
    retrieval: RetrievalPipeline,
    parent_span: Any = None,
) -> list[dict[str, Any]]:
    """Search the wiki corpus and return ranked chunk dicts for the LLM."""
    chunks = await retrieval.retrieve(
        query,
        game_version=game_version,
        k=k,
        parent_observation=parent_span,
    )
    return [
        {
            "page_title": c.page_title,
            "section": c.section,
            "content": c.content,
            "source_url": c.source_url,
            "score": c.score,
        }
        for c in chunks
    ]


def analyze_loadout(
    state: StatePayload,
    *,
    classifier: ItemClassifier = DEFAULT_CLASSIFIER,
) -> dict[str, Any]:
    """Detect player class from equipped items via the ItemClassifier (D-009).

    Resolves each gear item by ``item_id`` first (Cargo weapon index / armor
    bridge), falling back to ``name`` (curated map). The default classifier is
    curated-only (CI-safe); production injects a Cargo-backed one.
    """
    equipped: list[ItemRef] = list(state.gear.armor)
    if state.gear.weapon:
        equipped.append(state.gear.weapon)
    equipped.extend(state.gear.accessories)

    votes: dict[str, int] = {c: 0 for c in _CLASSES}
    for item in equipped:
        cls = classifier.classify(item_id=item.item_id, name=item.name)
        if cls:
            votes[cls] += 1

    total = sum(votes.values())
    if total == 0:
        return {
            "class": None,
            "confidence": "low",
            "progression_stage": _progression_stage(state),
            "needs_llm_fallback": True,
        }

    best = max(votes, key=lambda c: votes[c])
    ratio = votes[best] / total
    confidence = "high" if ratio >= 0.7 else ("medium" if ratio >= 0.4 else "low")
    return {
        "class": best,
        "confidence": confidence,
        "progression_stage": _progression_stage(state),
        "needs_llm_fallback": ratio < 0.4,
    }


def suggest_next_boss(state: StatePayload) -> dict[str, str]:
    """Return the next recommended boss based on world progression state."""
    downed = {_normalize(b) for b in state.world.downed_bosses}

    if not state.world.hardmode:
        if "eyeofcthulhu" not in downed:
            return {
                "next_boss": "Eye of Cthulhu",
                "rationale": (
                    "First progression boss. Requires 200+ HP"
                    " and at least silver/tungsten gear."
                ),
            }
        if "eaterofworlds" not in downed and "brainofcthulhu" not in downed:
            return {
                "next_boss": "Eater of Worlds / Brain of Cthulhu",
                "rationale": (
                    "Drops Shadow Scales or Tissue Samples needed"
                    " for Nightmare/Crimtane armor."
                ),
            }
        if "skeletron" not in downed:
            return {
                "next_boss": "Skeletron",
                "rationale": (
                    "Unlocks the Dungeon and the Clothier NPC."
                    " Required to access Dungeon loot."
                ),
            }
        return {
            "next_boss": "Wall of Flesh",
            "rationale": (
                "Final pre-Hardmode boss. Defeating it activates Hardmode"
                " and begins the Hallow/Corruption spread."
            ),
        }

    # Post-HM
    has_destroyer = "thedestroyer" in downed or "destroyer" in downed
    has_twins = "thetwins" in downed or "twins" in downed
    has_sp = "skeletronprime" in downed
    if not (has_destroyer and has_twins and has_sp):
        return {
            "next_boss": (
                "Mechanical Bosses (The Destroyer, The Twins, Skeletron Prime)"
            ),
            "rationale": (
                "All three must be defeated to spawn Plantera"
                " and access the Jungle Temple."
            ),
        }
    if "plantera" not in downed:
        return {
            "next_boss": "Plantera",
            "rationale": (
                "Drops the Temple Key (Golem access) and powerful weapons"
                " like the Grenade Launcher."
            ),
        }
    if "golem" not in downed:
        return {
            "next_boss": "Golem",
            "rationale": (
                "Drops the Picksaw and Sun Stone."
                " Defeating it lets the Lunatic Cultist spawn."
            ),
        }
    if "lunaticcultist" not in downed and "cultist" not in downed:
        return {
            "next_boss": "Lunatic Cultist",
            "rationale": (
                "Defeating it starts the Celestial Pillars event,"
                " the gateway to Moon Lord."
            ),
        }
    return {
        "next_boss": "Moon Lord",
        "rationale": (
            "Final boss. Drops Meowmere, S.D.M.G., Last Prism,"
            " and other endgame weapons."
        ),
    }


def tool_result_content(result: Any) -> str:
    """Serialize a tool result to a JSON string for the Anthropic tool_result block."""
    return json.dumps(result)
