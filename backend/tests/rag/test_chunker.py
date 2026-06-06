"""Unit tests for app/rag/chunker.py.  No live network, no live DB."""

from typing import Any

from app.rag.chunker import (
    BROKEN_BAR,
    _normalize_section_name,
    _token_count,
    _use_time_label,
    _window,
    chunk_id,
    chunk_page,
    parse_recipe_args,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _page(
    title: str = "Test Item",
    page_id: int = 1,
    wikitext: str = "",
    is_disambiguation: bool = False,
    revision_id: int = 100,
    source_url: str = "https://terraria.wiki.gg/wiki/Test_Item",
) -> dict[str, Any]:
    return {
        "title": title,
        "page_id": page_id,
        "revision_id": revision_id,
        "source_url": source_url,
        "wikitext": wikitext,
        "is_disambiguation": is_disambiguation,
        "namespace": 0,
        "timestamp": "2024-01-01T00:00:00Z",
    }


def _chunk_page(
    page: dict[str, Any],
    cargo_items: dict[str, dict[str, str]] | None = None,
    cargo_recipes: dict[str, list[dict[str, str]]] | None = None,
) -> list[Any]:
    chunks, _ = chunk_page(
        page,
        game_version="1.4.4.9",
        cargo_items=cargo_items or {},
        cargo_recipes=cargo_recipes or {},
    )
    return chunks


# ── Use-time labels (wiki-sourced thresholds) ─────────────────────────────────


def test_use_time_labels_wiki_thresholds() -> None:
    assert _use_time_label(7) == "Insanely fast"  # Megashark
    assert _use_time_label(8) == "Insanely fast"
    assert _use_time_label(9) == "Very fast"
    assert _use_time_label(20) == "Very fast"
    assert _use_time_label(21) == "Fast"
    assert _use_time_label(25) == "Fast"
    assert _use_time_label(26) == "Average"
    assert _use_time_label(30) == "Average"
    assert _use_time_label(31) == "Slow"
    assert _use_time_label(45) == "Very slow"
    assert _use_time_label(46) == "Extremely slow"
    assert _use_time_label(56) == "Snail"


# ── Windowing / token budget ──────────────────────────────────────────────────


def test_single_short_section_one_chunk() -> None:
    text = " ".join(["word"] * 80)  # ~104 approx tokens — under 180
    windows = _window(text)
    assert len(windows) == 1
    assert windows[0] == text


def test_long_section_split_into_windows() -> None:
    # ~520 approx tokens → multiple windows
    text = " ".join(["word"] * 400)
    windows = _window(text)
    assert len(windows) > 1
    # Each window should be under the target
    for w in windows:
        assert _token_count(w) <= 180 + 10  # small tolerance for word boundaries


def test_min_token_filter_discards_thin_section() -> None:
    text = "Very short."  # well under 20 tokens
    assert _window(text) == []


# ── Disambiguation filter ─────────────────────────────────────────────────────


def test_disambiguation_page_skipped() -> None:
    page = _page(
        wikitext="{{Disambiguation}}\n* [[A]]\n* [[B]]", is_disambiguation=True
    )
    chunks = _chunk_page(page)
    assert chunks == []


# ── Chunk index monotonicity ──────────────────────────────────────────────────


def test_chunk_index_monotone_across_sections() -> None:
    wikitext = (
        "Intro text about the item. " * 5
        + "\n== Notes ==\n"
        + "Important notes here. " * 5
        + "\n== Tips ==\n"
        + "Useful tips for players. " * 5
    )
    chunks = _chunk_page(_page(wikitext=wikitext))
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)


# ── Section title prepend ─────────────────────────────────────────────────────


def test_section_title_prepended_to_embed_text() -> None:
    wikitext = "== Notes ==\nThis item has special notes. " * 5
    chunks = _chunk_page(_page(title="Megashark", wikitext=wikitext))
    notes_chunks = [c for c in chunks if c.section == "Notes"]
    assert notes_chunks, "expected at least one Notes chunk"
    assert notes_chunks[0].embed_text.startswith("Megashark — Notes\n")


# ── Cargo stats synthesis ─────────────────────────────────────────────────────


def test_item_cargo_synthesis_full_stats() -> None:
    row: dict[str, str] = {
        "_pageName": "Megashark",
        "damage": "25",
        "damagetype": "Ranged",
        "usetime": "7",
        "knockback": "1",
        "velocity": "10",
        "critical": "4",
        "hardmode": "1",
        "listcat": "Guns^Scope^Ranged weapons^craftable items",
        "type": "weapon",
        "tooltip": "",
        "autoswing": "1",
    }
    chunks = _chunk_page(
        _page(title="Megashark"),
        cargo_items={"Megashark": row},
    )
    stats = [c for c in chunks if c.section == "stats"]
    assert stats, "expected a stats chunk"
    content = stats[0].content
    assert "25" in content  # damage
    assert "7" in content  # usetime
    assert "Insanely fast" in content  # correct wiki label for usetime=7
    assert "1" in content  # knockback
    assert "10" in content  # velocity


def test_item_cargo_tooltip_html_stripped() -> None:
    row: dict[str, str] = {
        "_pageName": "Megashark",
        "damage": "25",
        "damagetype": "Ranged",
        "usetime": "7",
        "knockback": "0",
        "velocity": "0",
        "critical": "0",
        "hardmode": "1",
        "listcat": "Guns",
        "type": "weapon",
        "tooltip": (
            '<span class="gameText">50% chance to save ammo<br/>'
            "&#39;Minishark&#39;s older brother&#39;</span>"
        ),
        "autoswing": "0",
    }
    chunks = _chunk_page(
        _page(title="Megashark"),
        cargo_items={"Megashark": row},
    )
    stats = [c for c in chunks if c.section == "stats"]
    assert stats
    content = stats[0].content
    assert "<span" not in content
    assert "&#39;" not in content
    assert "50% chance to save ammo" in content
    assert "Minishark's older brother" in content


def test_listcat_caret_split_uses_first() -> None:
    row: dict[str, str] = {
        "_pageName": "Megashark",
        "damage": "0",
        "damagetype": "",
        "usetime": "0",
        "knockback": "0",
        "velocity": "0",
        "critical": "0",
        "hardmode": "1",
        "listcat": "Guns^Scope^Ranged weapons^craftable items",
        "type": "weapon",
        "tooltip": "",
        "autoswing": "0",
    }
    chunks = _chunk_page(
        _page(title="Megashark"),
        cargo_items={"Megashark": row},
    )
    stats = [c for c in chunks if c.section == "stats"]
    assert stats
    # Primary category "Guns" should surface in the opening phrase.
    assert "Guns" in stats[0].content


# ── Recipe args parsing ───────────────────────────────────────────────────────


def test_recipe_args_broken_bar_not_pipe() -> None:
    # Document the encoding explicitly — must use U+00A6, not ASCII pipe.
    assert BROKEN_BAR == "¦"
    assert BROKEN_BAR != "|"

    result = parse_recipe_args("Minishark¦1^Shark Fin¦5")
    assert result == [("Minishark", "1"), ("Shark Fin", "5")]

    # ASCII pipe must NOT parse as the separator.
    ascii_pipe_result = parse_recipe_args("Minishark|1^Shark Fin|5")
    assert ascii_pipe_result == []


def test_multi_recipe_emits_multiple_chunks() -> None:
    recipes = [
        {
            "result": "Broken Hero Sword",
            "amount": "1",
            "station": "Work Bench",
            "args": "Wood¦5",
        },
        {
            "result": "Broken Hero Sword",
            "amount": "1",
            "station": "Mythril Anvil",
            "args": "Souls¦10^Iron¦2",
        },
    ]
    chunks = _chunk_page(
        _page(title="Broken Hero Sword"),
        cargo_recipes={"Broken Hero Sword": recipes},
    )
    recipe_chunks = [c for c in chunks if c.section == "recipe"]
    assert len(recipe_chunks) == 2
    # chunk_index must be sequential
    assert recipe_chunks[0].chunk_index < recipe_chunks[1].chunk_index


def test_cargo_item_without_wiki_page_skipped() -> None:
    # Cargo row for "Phantom Item" but no wiki page provided — no chunk, no error.
    row: dict[str, str] = {
        "_pageName": "Phantom Item",
        "damage": "99",
        "damagetype": "Melee",
        "usetime": "10",
        "knockback": "5",
        "velocity": "0",
        "critical": "4",
        "hardmode": "1",
        "listcat": "Swords",
        "type": "weapon",
        "tooltip": "",
        "autoswing": "1",
    }
    # We pass a page whose title does NOT match the Cargo row.
    chunks = _chunk_page(
        _page(title="Different Page"),
        cargo_items={"Phantom Item": row},
    )
    # Only prose chunks (if any) — no stats chunk for "Phantom Item".
    assert all(c.page_title == "Different Page" for c in chunks)
    assert all(
        c.section != "stats" or c.content.startswith("Different") for c in chunks
    )


def test_recipe_orphan_result_logged(tmp_path: Any) -> None:
    # This is tested at the build_corpus.py level (orphan_recipes.jsonl).
    # Here we just confirm parse_recipe_args handles empty args gracefully.
    assert parse_recipe_args("") == []
    assert parse_recipe_args("   ") == []


# ── NPC template synthesis ────────────────────────────────────────────────────


def test_npc_infobox_modes_extraction() -> None:
    wikitext = (
        "{{npc infobox\n"
        "| auto = 4\n"
        "| type = Boss\n"
        "| environment = Surface+Night\n"
        "| ai = Eye of Cthulhu AI\n"
        "| damage = {{modes|wrap=no|23|{{expert|36}}}}\n"
        "| defense = {{modes|wrap=no|12}}\n"
        "| knockback = 100%\n"
        "| immune1 = Confused\n"
        "}}\n"
        "The Eye of Cthulhu is a pre-Hardmode boss.\n"
    )
    chunks = _chunk_page(_page(title="Eye of Cthulhu", wikitext=wikitext))
    stats = [c for c in chunks if c.section == "stats"]
    assert stats, "expected NPC stats chunk"
    content = stats[0].content
    assert "23" in content  # Classic damage
    assert "Confused" in content  # immune
    assert "Surface+Night" in content or "Surface" in content


def test_drop_table_synthesis_groups() -> None:
    wikitext = (
        "{{npc infobox\n"
        "| type = Boss\n"
        "| Binoculars\n"
        "| 1\n"
        "| 2.5% @normal\n"
        "| :group:start\n"
        "| Only in Corrupt worlds\n"
        "| Demonite Ore\n"
        "| 30-90\n"
        "| 100% @normal\n"
        "| :group:end\n"
        "| -----\n"
        "}}\n"
    )
    chunks = _chunk_page(_page(title="Eye of Cthulhu", wikitext=wikitext))
    drops = [c for c in chunks if c.section == "drops"]
    assert drops, "expected drops chunk"
    content = drops[0].content
    assert "Binoculars" in content
    assert "Demonite Ore" in content
    assert "Corrupt" in content


def test_drop_table_expert_loot() -> None:
    wikitext = (
        "{{npc infobox\n"
        "| type = Boss\n"
        "| Lesser Healing Potion\n"
        "| 5-15\n"
        "| 100%\n"
        "| :loot:start\n"
        "| ---\n"
        "| - #expert\n"
        "| Shield of Cthulhu\n"
        "| 1\n"
        "| 100% #expert\n"
        "| :loot:end\n"
        "| ---\n"
        "}}\n"
    )
    chunks = _chunk_page(_page(title="Eye of Cthulhu", wikitext=wikitext))
    drops = [c for c in chunks if c.section == "drops"]
    assert drops, "expected drops chunk"
    content = drops[0].content
    assert "Lesser Healing Potion" in content
    assert "Shield of Cthulhu" in content
    assert "Expert" in content


def test_cargo_lookup_detected_on_item() -> None:
    # Item infobox with auto=NNN and no explicit damage → no damage value
    # in the stats chunk.
    row: dict[str, str] = {
        "_pageName": "Wooden Sword",
        "damage": "",
        "damagetype": "",
        "usetime": "",
        "knockback": "",
        "velocity": "",
        "critical": "",
        "hardmode": "",
        "listcat": "Broadswords",
        "type": "weapon",
        "tooltip": "",
        "autoswing": "",
    }
    chunks = _chunk_page(
        _page(title="Wooden Sword"),
        cargo_items={"Wooden Sword": row},
    )
    stats = [c for c in chunks if c.section == "stats"]
    # A stats chunk is still emitted (listcat/type are present).
    assert stats
    # But no damage number should appear.
    assert "Damage:" not in stats[0].content


def test_stats_chunk_under_token_budget() -> None:
    row: dict[str, str] = {
        "_pageName": "Megashark",
        "damage": "25",
        "damagetype": "Ranged",
        "usetime": "7",
        "knockback": "1",
        "velocity": "10",
        "critical": "4",
        "hardmode": "1",
        "listcat": "Guns",
        "type": "weapon",
        "tooltip": "50% chance to save ammo",
        "autoswing": "1",
    }
    chunks = _chunk_page(
        _page(title="Megashark"),
        cargo_items={"Megashark": row},
    )
    stats = [c for c in chunks if c.section == "stats"]
    assert stats
    from app.rag.chunker import _token_count

    assert _token_count(stats[0].content) <= 180


def test_chunk_index_sequential_across_stat_and_prose() -> None:
    row: dict[str, str] = {
        "_pageName": "Megashark",
        "damage": "25",
        "damagetype": "Ranged",
        "usetime": "7",
        "knockback": "0",
        "velocity": "0",
        "critical": "0",
        "hardmode": "1",
        "listcat": "Guns",
        "type": "weapon",
        "tooltip": "",
        "autoswing": "0",
    }
    wikitext = (
        "The Megashark is a Hardmode gun. " * 6
        + "\n== Tips ==\nUse with Crystal Bullets. " * 6
    )
    chunks = _chunk_page(
        _page(title="Megashark", wikitext=wikitext),
        cargo_items={"Megashark": row},
    )
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)
    # Stats chunk must come first.
    assert chunks[0].section == "stats"


# ── Recipe qty=1 not dropped ─────────────────────────────────────────────────


def test_recipe_synthesis_qty_one_not_dropped() -> None:
    """qty=1 must appear in the ingredient string, not be silently dropped."""
    row: dict[str, str] = {
        "result": "Megashark",
        "amount": "1",
        "station": "Mythril Anvil",
        "args": "Minishark¦1^Soul of Might¦20",
    }
    chunks = _chunk_page(
        _page(title="Megashark"),
        cargo_recipes={"Megashark": [row]},
    )
    recipe = [c for c in chunks if c.section == "recipe"]
    assert recipe, "expected a recipe chunk"
    content = recipe[0].content
    assert "1 Minishark" in content
    assert "20 Soul of Might" in content


# ── Multilingual section normalisation ───────────────────────────────────────


def test_normalize_section_name_ascii_unchanged() -> None:
    assert _normalize_section_name("Notes") == "Notes"
    assert _normalize_section_name("Tips") == "Tips"
    assert _normalize_section_name("History") == "History"


def test_normalize_section_name_non_ascii_becomes_misc() -> None:
    assert _normalize_section_name("Catatan") == "misc"  # Indonesian
    assert _normalize_section_name("Mẹo") == "misc"  # Vietnamese
    assert _normalize_section_name("Ghi chú") == "misc"  # Vietnamese
    assert _normalize_section_name("更新日誌") == "misc"  # Chinese


def test_non_ascii_section_content_still_embedded() -> None:
    """Non-ASCII heading normalises to 'misc' but the content is not discarded."""
    wikitext = "== Catatan ==\n" + "Important item notes here. " * 5
    chunks = _chunk_page(_page(title="Test Item", wikitext=wikitext))
    misc_chunks = [c for c in chunks if c.section == "misc"]
    assert misc_chunks, "expected a 'misc' chunk for non-ASCII heading"


# ── Deterministic chunk IDs ───────────────────────────────────────────────────


def test_deterministic_chunk_ids_same_input_same_uuid() -> None:
    id1 = chunk_id(42, 3, "1.4.4.9")
    id2 = chunk_id(42, 3, "1.4.4.9")
    assert id1 == id2


def test_deterministic_chunk_ids_different_inputs_different_uuids() -> None:
    base = chunk_id(42, 3, "1.4.4.9")
    assert chunk_id(42, 4, "1.4.4.9") != base  # different chunk_index
    assert chunk_id(43, 3, "1.4.4.9") != base  # different page_id
    assert chunk_id(42, 3, "1.4.4.8") != base  # different game_version


def test_deterministic_chunk_ids_rebuild_idempotency() -> None:
    """chunk_page called twice on the same fixture produces byte-identical IDs."""
    wikitext = (
        "Intro text about the item. " * 5
        + "\n== Notes ==\n"
        + "Important notes here. " * 5
        + "\n== Tips ==\n"
        + "Useful tips for players. " * 5
    )
    page = _page(title="Test Item", page_id=99, wikitext=wikitext)
    chunks_a = _chunk_page(page)
    chunks_b = _chunk_page(page)
    assert len(chunks_a) == len(chunks_b)
    assert len(chunks_a) > 0, "fixture page must produce at least one chunk"
    for ca, cb in zip(chunks_a, chunks_b):
        assert chunk_id(ca.page_id, ca.chunk_index, "1.4.4.9") == chunk_id(
            cb.page_id, cb.chunk_index, "1.4.4.9"
        )
