"""Unit tests for app/agent/class_detection.py (Phase 3.3 commit 1).

No real Cargo data (gitignored — finding A4). A synthetic items.json fixture
covers one weapon per damagetype, a tool that carries a damagetype, and an
armor row with no damagetype.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.agent.class_detection import (
    DEFAULT_CLASSIFIER,
    ItemClassifier,
    llm_classify,
)
from app.agent.graph import build_agent_graph
from app.agent.tools import analyze_loadout
from app.core.prompts import LoadedPrompts
from app.domain.bot import GearState, ItemRef, StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.pipeline import RetrievalPipeline

# ── Synthetic Cargo fixture ───────────────────────────────────────────────────
# One weapon per damagetype + one tool with a damagetype (must be excluded,
# A2) + one armor row whose name is in the curated map (no damagetype, A3).
_SYNTHETIC_ITEMS: list[dict[str, str]] = [
    {"name": "Test Sword", "itemid": "100", "damagetype": "Melee", "type": "weapon"},
    {"name": "Test Gun", "itemid": "101", "damagetype": "Ranged", "type": "weapon"},
    {"name": "Test Staff", "itemid": "102", "damagetype": "Magic", "type": "weapon"},
    {"name": "Test Whip", "itemid": "103", "damagetype": "Summon", "type": "weapon"},
    # Multi-tag `type` (Minishark's real shape, "weapon^crafting material"): the
    # `^`-join must still resolve as a weapon via _is_weapon_type (A2 / Issue 2).
    {
        "name": "Test Repeater",
        "itemid": "104",
        "damagetype": "Ranged",
        "type": "weapon^crafting material",
    },
    # Tool that carries a damagetype — must NOT be classified (type != weapon).
    {"name": "Test Pickaxe", "itemid": "200", "damagetype": "Melee", "type": "tool"},
    # Armor (no damagetype); name is in the curated map → melee.
    {"name": "Molten Helmet", "itemid": "201", "damagetype": "", "type": "armor"},
]


def _write_items(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    p = tmp_path / "items.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


# ── Cargo weapon resolution (damagetype) ──────────────────────────────────────


def test_cargo_weapon_resolves_via_damagetype(tmp_path: Path) -> None:
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    clf = ItemClassifier.from_cargo_file(path, min_items=1)

    # By item_id
    assert clf.classify(item_id=100) == "melee"
    assert clf.classify(item_id=101) == "ranger"
    assert clf.classify(item_id=102) == "mage"
    assert clf.classify(item_id=103) == "summoner"
    # By name
    assert clf.classify(name="Test Gun") == "ranger"
    assert clf.classify(name="test staff") == "mage"  # case-insensitive
    assert clf.cargo_weapon_count == 5  # 4 clean + 1 multi-tag type


def test_multi_tag_type_resolves_as_weapon(tmp_path: Path) -> None:
    """`type="weapon^crafting material"` (Minishark shape) resolves by id and name."""
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    clf = ItemClassifier.from_cargo_file(path, min_items=1)
    assert clf.classify(item_id=104) == "ranger"
    assert clf.classify(name="Test Repeater") == "ranger"


def test_tool_with_damagetype_excluded(tmp_path: Path) -> None:
    """A pickaxe carries damagetype=Melee but type=tool → no class (A2)."""
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    clf = ItemClassifier.from_cargo_file(path, min_items=1)

    assert clf.classify(item_id=200) is None
    assert clf.classify(name="Test Pickaxe") is None


def test_armor_falls_through_to_curated(tmp_path: Path) -> None:
    """Armor has no Cargo class signal (A3); resolves via the curated map."""
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    clf = ItemClassifier.from_cargo_file(path, min_items=1)

    # By name directly against the curated map.
    assert clf.classify(name="Molten Helmet") == "melee"
    # By item_id: Cargo id→name bridge then curated lookup.
    assert clf.classify(item_id=201) == "melee"


def test_unknown_item_returns_none(tmp_path: Path) -> None:
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    clf = ItemClassifier.from_cargo_file(path, min_items=1)

    assert clf.classify(item_id=99999) is None
    assert clf.classify(name="Nonexistent Doohickey") is None
    assert clf.classify() is None


# ── Resolution precedence ─────────────────────────────────────────────────────


def test_item_id_precedence_over_name() -> None:
    """item_id → Cargo weapon wins over a conflicting curated name match."""
    clf = ItemClassifier(
        curated={"ambiguous blade": "melee"},
        cargo_weapon_by_id={300: "ranger"},
    )
    # item_id resolves via Cargo (ranger), even though the name is curated melee.
    assert clf.classify(item_id=300, name="Ambiguous Blade") == "ranger"
    # name alone resolves via the curated map (melee).
    assert clf.classify(name="Ambiguous Blade") == "melee"


def test_cargo_weapon_wins_over_curated_by_name() -> None:
    """A name that is a Cargo weapon beats the curated map for the same name."""
    clf = ItemClassifier(
        curated={"flux blade": "melee"},
        cargo_weapon_by_name={"flux blade": "ranger"},
    )
    assert clf.classify(name="Flux Blade") == "ranger"


# ── DEFAULT (curated-only) classifier — CI-safe, no Cargo ─────────────────────


def test_default_classifier_is_curated_only() -> None:
    """DEFAULT_CLASSIFIER has no Cargo data but still resolves curated items."""
    assert DEFAULT_CLASSIFIER.cargo_weapon_count == 0
    assert DEFAULT_CLASSIFIER.classify(name="megashark") == "ranger"
    assert DEFAULT_CLASSIFIER.classify(name="Molten Helmet") == "melee"
    assert DEFAULT_CLASSIFIER.classify(name="bee breastplate") == "summoner"
    assert DEFAULT_CLASSIFIER.classify(name="meteor helmet") == "mage"


# ── Refuse-to-boot ────────────────────────────────────────────────────────────


def test_refuse_to_boot_missing_items_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        ItemClassifier.from_cargo_file(tmp_path / "nonexistent.json")


def test_refuse_to_boot_truncated_items(tmp_path: Path) -> None:
    """6-row synthetic file fails the default min_items=100 sanity check."""
    path = _write_items(tmp_path, _SYNTHETIC_ITEMS)
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        ItemClassifier.from_cargo_file(path)  # default min_items=100


def test_refuse_to_boot_not_a_json_array(tmp_path: Path) -> None:
    path = tmp_path / "items.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        ItemClassifier.from_cargo_file(path, min_items=1)


def test_refuse_to_boot_unparseable(tmp_path: Path) -> None:
    path = tmp_path / "items.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        ItemClassifier.from_cargo_file(path, min_items=1)


# ── analyze_loadout with a Cargo-backed classifier (commit 3 swap) ────────────


def test_analyze_loadout_resolves_cargo_weapon_by_item_id() -> None:
    """A weapon known only to Cargo (not in the curated map) resolves by item_id."""
    # 9999 is not in CURATED_ITEM_CLASS; only the Cargo index knows it.
    clf = ItemClassifier(cargo_weapon_by_id={9999: "ranger"})
    assert DEFAULT_CLASSIFIER.classify(item_id=9999) is None  # curated-only: unknown

    state = StatePayload(gear=GearState(weapon=ItemRef(item_id=9999, name="")))
    result = analyze_loadout(state, classifier=clf)
    assert result["class"] == "ranger"
    assert result["confidence"] == "high"
    assert result["needs_llm_fallback"] is False


def test_analyze_loadout_resolves_armor_via_cargo_id_bridge() -> None:
    """Mod sends armor by item_id only → Cargo id→name bridge → curated class."""
    # Cargo knows item_id 5001 is named "Molten Helmet" (curated → melee), but
    # carries no class for it (armor has no damagetype, A3).
    clf = ItemClassifier(
        curated={"molten helmet": "melee"},
        cargo_name_by_id={5001: "Molten Helmet"},
    )
    state = StatePayload(gear=GearState(armor=[ItemRef(item_id=5001, name="")]))
    result = analyze_loadout(state, classifier=clf)
    assert result["class"] == "melee"


def test_analyze_loadout_default_classifier_matches_phase_3_2_behavior() -> None:
    """Name-only gear with the default classifier reproduces the curated result."""
    state = StatePayload(
        gear=GearState(
            armor=[ItemRef(name="molten helmet"), ItemRef(name="molten greaves")]
        )
    )
    result = analyze_loadout(state)  # no classifier → DEFAULT_CLASSIFIER
    assert result["class"] == "melee"


# ── LLM zero-shot fallback (llm_classify) ─────────────────────────────────────


def _mock_anthropic(reply: str) -> AnthropicClient:
    client = MagicMock(spec=AnthropicClient)
    client.chat = AsyncMock(return_value=(reply, 80, 8))
    return client


async def test_llm_classify_recognized_class() -> None:
    anthropic = _mock_anthropic("ranger")
    result = await llm_classify(StatePayload(), anthropic=anthropic, prompt="p")
    assert result == {"class": "ranger", "confidence": "llm-zero-shot"}


async def test_llm_classify_unknown_reply() -> None:
    anthropic = _mock_anthropic("unknown")
    result = await llm_classify(StatePayload(), anthropic=anthropic, prompt="p")
    assert result == {"class": None, "confidence": "llm-zero-shot-unknown"}


async def test_llm_classify_parses_first_recognized_word_in_noisy_reply() -> None:
    """Parse rule: scan word tokens, return the first recognized class word."""
    anthropic = _mock_anthropic("I think melee")
    result = await llm_classify(StatePayload(), anthropic=anthropic, prompt="p")
    assert result == {"class": "melee", "confidence": "llm-zero-shot"}


async def test_llm_classify_offvocab_reply_is_unknown() -> None:
    anthropic = _mock_anthropic("warrior")
    result = await llm_classify(StatePayload(), anthropic=anthropic, prompt="p")
    assert result == {"class": None, "confidence": "llm-zero-shot-unknown"}


async def test_llm_classify_uses_haiku_and_max_tokens_8() -> None:
    anthropic = _mock_anthropic("mage")
    await llm_classify(StatePayload(), anthropic=anthropic, prompt="sys-prompt")
    anthropic.chat.assert_awaited_once()  # type: ignore[attr-defined]
    kwargs = anthropic.chat.call_args.kwargs  # type: ignore[attr-defined]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["max_tokens"] == 8
    assert kwargs["system"] == "sys-prompt"
    assert kwargs["span_name"] == "agent.llm_classify"


# ── Graph-level: execute_tools fires the fallback on cold-start ───────────────


def _fallback_prompts() -> LoadedPrompts:
    return LoadedPrompts(
        router="r",
        faq_answer="f",
        agent_system="a" * 100,
        class_fallback="c" * 100,
    )


async def test_execute_tools_fires_llm_fallback_on_empty_gear() -> None:
    """Empty gear → analyze_loadout needs_llm_fallback → llm_classify merged in."""
    anthropic = MagicMock(spec=AnthropicClient)
    anthropic.chat_with_tools = AsyncMock(
        side_effect=[
            (
                [
                    ToolUseBlock(
                        id="tu1", name="analyze_loadout", input={}, type="tool_use"
                    )
                ],
                "tool_use",
                100,
                10,
            ),
            ([TextBlock(text="You lean ranger.", type="text")], "end_turn", 80, 20),
        ]
    )
    anthropic.chat = AsyncMock(return_value=("ranger", 80, 8))
    retrieval = MagicMock(spec=RetrievalPipeline)
    retrieval.retrieve = AsyncMock(return_value=[])

    graph = build_agent_graph(retrieval, anthropic, _fallback_prompts())
    result = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "what class am I?"}],
            "chunks_seen": [],
            "iteration_count": 0,
            "state_payload": StatePayload(),  # empty gear → cold start
        }
    )

    # The llm_classify call fired exactly once.
    anthropic.chat.assert_awaited_once()

    # The analyze_loadout tool_result carries the merged llm_fallback class.
    merged_found = False
    for msg in result["messages"]:
        content = msg.get("content")
        if msg.get("role") == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    payload = json.loads(block["content"])
                    if payload.get("llm_fallback", {}).get("class") == "ranger":
                        merged_found = True
    assert merged_found
