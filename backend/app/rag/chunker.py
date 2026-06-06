"""Wikitext + Cargo → List[ChunkRecord].

Chunking pipeline per page (in order):
  1. Skip disambiguation pages.
  2. Cargo stats chunk  (section="stats")  — from Items Cargo row if present.
  3. Recipe chunks      (section="recipe") — one per Recipes Cargo row.
  4. NPC template synthesis (section="stats", "drops") — from wikitext infobox.
  5. Prose sections — structural split at L2 headings, sliding-window fallback.

Chunk indices are sequential across all chunk types for a given page.
"""

from __future__ import annotations

import html as html_lib
import re
import uuid
from typing import Any

import mwparserfromhell

from app.rag.models import ChunkRecord

# ── Use-time speed labels (official wiki thresholds from Use_time article) ──
# Source: https://terraria.wiki.gg/wiki/Use_time
_USE_TIME_LABELS: list[tuple[int, str]] = [
    (8, "Insanely fast"),
    (20, "Very fast"),
    (25, "Fast"),
    (30, "Average"),
    (35, "Slow"),
    (45, "Very slow"),
    (55, "Extremely slow"),
    (10000, "Snail"),
]

# ── Token budget ─────────────────────────────────────────────────────────────
# all-MiniLM-L6-v2 has a 256-token context window.  We target 180 tokens
# (76-token buffer for special tokens + heading prepend).
_TARGET_TOKENS = 180
_OVERLAP_TOKENS = 30
_MIN_TOKENS = 20

# Broken bar (U+00A6) — the separator in Cargo's `args` field.
BROKEN_BAR = "¦"


# ── Stable chunk identity ─────────────────────────────────────────────────────


def chunk_id(page_id: int, chunk_index: int, game_version: str) -> uuid.UUID:
    """Return the deterministic UUID for a chunk.

    Uses uuid5(NAMESPACE_OID, "{page_id}:{chunk_index}:{game_version}") so the
    same corpus input always produces the same row ID, surviving volume wipes.
    NAMESPACE_OID is the stdlib constant uuid.NAMESPACE_OID — no custom namespace.
    """
    return uuid.uuid5(uuid.NAMESPACE_OID, f"{page_id}:{chunk_index}:{game_version}")


# ── Public entry point ────────────────────────────────────────────────────────


def chunk_page(
    page: dict[str, Any],
    game_version: str,
    cargo_items: dict[str, dict[str, str]],
    cargo_recipes: dict[str, list[dict[str, str]]],
) -> tuple[list[ChunkRecord], bool]:
    """Chunk one page JSON into ChunkRecords.

    Returns (chunks, is_cargo_only) where is_cargo_only is True when the page
    had no literal stats in its wikitext and relied on Cargo for its stats chunk.
    """
    if page.get("is_disambiguation"):
        return [], False

    title = page["title"]
    page_id = page["page_id"]
    revision_id = page.get("revision_id", 0)
    source_url = page.get("source_url", "")
    wikitext: str = page.get("wikitext", "")

    chunks: list[ChunkRecord] = []
    idx = 0

    def _make(section: str, content: str) -> ChunkRecord:
        nonlocal idx
        embed_text = f"{title} — {section}\n{content}"
        rec = ChunkRecord(
            page_id=page_id,
            chunk_index=idx,
            revision_id=revision_id,
            source_url=source_url,
            game_version=game_version,
            page_title=title,
            section=section,
            content=content,
            embed_text=embed_text,
        )
        idx += 1
        return rec

    # 1. Cargo stats chunk (items only — NPC stats come from wikitext).
    is_cargo_only = False
    if title in cargo_items:
        row = cargo_items[title]
        stats_text = _synthesize_item_stats(title, row)
        if stats_text:
            chunks.append(_make("stats", stats_text))
            is_cargo_only = True

    # 2. Recipe chunks.
    for recipe_row in cargo_recipes.get(title, []):
        recipe_text = _synthesize_recipe(title, recipe_row)
        if recipe_text:
            chunks.append(_make("recipe", recipe_text))

    # 3 + 4 + 5. Parse wikitext.
    if wikitext:
        wikicode = mwparserfromhell.parse(wikitext)

        # NPC template synthesis (adds stats / drops chunks before prose).
        npc_chunks = _synthesize_npc(title, wikicode)
        for section_name, text in npc_chunks:
            for window in _window(text):
                chunks.append(_make(section_name, window))

        # Prose sections.
        sections = wikicode.get_sections(levels=[2], include_lead=True)
        for section in sections:
            headings = section.filter_headings()
            raw_heading = (
                headings[0].title.strip_code().strip() if headings else "intro"
            )
            section_name = _normalize_section_name(raw_heading)
            plain = section.strip_code(normalize=True, collapse=True).strip()
            # Remove the heading text itself from the body.
            if headings:
                heading_text = headings[0].title.strip_code().strip()
                plain = plain.replace(heading_text, "").strip()
            for window in _window(plain):
                chunks.append(_make(section_name, window))

    return chunks, is_cargo_only


# ── Use-time label ────────────────────────────────────────────────────────────


def _use_time_label(usetime: int) -> str:
    for threshold, label in _USE_TIME_LABELS:
        if usetime <= threshold:
            return label
    return "Snail"


# ── Item stats synthesis ──────────────────────────────────────────────────────


def _clean_html(val: str) -> str:
    stripped = re.sub(r"<[^>]+>", "", val).strip()
    return html_lib.unescape(stripped)


def _int_or_none(val: str) -> int | None:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _synthesize_item_stats(title: str, row: dict[str, str]) -> str:
    """Build a natural-language stats sentence from a Cargo Items row."""
    parts: list[str] = []

    hardmode = row.get("hardmode", "") == "1"
    listcat_raw = row.get("listcat", "")
    categories = [c.strip() for c in listcat_raw.split("^") if c.strip()]
    primary_cat = categories[0] if categories else ""
    item_type = row.get("type", "")

    # Opening phrase.
    hm = "Hardmode " if hardmode else ""
    cat_str = f"{primary_cat} " if primary_cat else ""
    type_str = item_type if item_type else "item"
    parts.append(f"{title} is a {hm}{cat_str}{type_str}.")

    # Numeric stats — only emit if non-zero.
    damage = _int_or_none(row.get("damage", ""))
    if damage:
        dmg_type = row.get("damagetype", "")
        dmg_str = f"Damage: {damage}"
        if dmg_type:
            dmg_str += f" ({dmg_type})"
        dmg_str += "."
        parts.append(dmg_str)

    usetime = _int_or_none(row.get("usetime", ""))
    if usetime:
        label = _use_time_label(usetime)
        parts.append(f"Use time: {usetime} ({label}).")

    knockback = _int_or_none(row.get("knockback", ""))
    if knockback is not None and knockback != 0:
        parts.append(f"Knockback: {knockback}.")

    velocity = _int_or_none(row.get("velocity", ""))
    if velocity:
        parts.append(f"Velocity: {velocity}.")

    crit = _int_or_none(row.get("critical", ""))
    if crit:
        parts.append(f"Critical chance bonus: {crit}%.")

    defense = _int_or_none(row.get("defense", ""))
    if defense:
        parts.append(f"Defense: {defense}.")

    mana = _int_or_none(row.get("mana", ""))
    if mana:
        parts.append(f"Mana cost: {mana}.")

    hheal = _int_or_none(row.get("hheal", ""))
    if hheal:
        parts.append(f"Health restored: {hheal}.")

    # Tooltip — strip HTML and unescape entities.
    tooltip_raw = row.get("tooltip", "")
    if tooltip_raw:
        tooltip = _clean_html(tooltip_raw)
        if tooltip:
            parts.append(tooltip)

    return " ".join(parts)


# ── Recipe synthesis ──────────────────────────────────────────────────────────


def parse_recipe_args(args: str) -> list[tuple[str, str]]:
    """Parse Cargo Recipes.args into (item_name, qty) pairs.

    Format: "Name¦qty^Name¦qty^..."
    The separator inside each pair is U+00A6 BROKEN BAR, not ASCII pipe.
    """
    if not args:
        return []
    result: list[tuple[str, str]] = []
    for pair in args.split("^"):
        parts = pair.split(BROKEN_BAR, 1)
        if len(parts) == 2:
            name, qty = parts[0].strip(), parts[1].strip()
            if name:
                result.append((name, qty))
    return result


def _synthesize_recipe(title: str, row: dict[str, str]) -> str:
    """Build a recipe sentence from a Cargo Recipes row."""
    args = row.get("args", "")
    ingredients = parse_recipe_args(args)
    if not ingredients:
        return ""

    station = row.get("station", "").strip()
    amount_str = row.get("amount", "1").strip()
    try:
        amount = int(amount_str)
    except ValueError:
        amount = 1

    ing_parts = [f"{qty} {name}" for name, qty in ingredients]
    ing_str = ", ".join(ing_parts)

    yields_str = f" (yields {amount})" if amount > 1 else ""
    at_str = f" at a {station}" if station else ""

    return f"{title}{yields_str} is crafted from {ing_str}{at_str}."


# ── NPC template synthesis ────────────────────────────────────────────────────

_MODES_RE = re.compile(r"\{\{modes\b", re.IGNORECASE)


def _extract_modes_first_positional(value: str) -> str | None:
    """Extract Classic-mode value from {{modes|wrap=no|X|...}} template string."""
    try:
        wc = mwparserfromhell.parse(value)
        templates = wc.filter_templates()
        if not templates:
            return None
        t = templates[0]
        if "modes" not in t.name.lower():
            return None
        positional = [p for p in t.params if not p.showkey]
        if not positional:
            return None
        raw = positional[0].value.strip_code().strip()
        # Strip inline HTML/annotation characters.
        raw = re.sub(r"<[^>]+>", "", raw).strip()
        return raw if raw else None
    except Exception:
        return None


def _synthesize_npc(title: str, wikicode: Any) -> list[tuple[str, str]]:
    """Extract NPC infobox stats and drop table from wikicode.

    Returns list of (section_name, text) pairs ready for windowing.
    """
    results: list[tuple[str, str]] = []
    npc_boxes = [
        t
        for t in wikicode.filter_templates()
        if "npc infobox" in t.name.strip().lower()
    ]
    if not npc_boxes:
        return results

    # Use the infobox with the most params (typically the primary / second form).
    box = max(npc_boxes, key=lambda t: len(t.params))

    def _param(name: str) -> str:
        try:
            return str(box.get(name).value).strip()
        except ValueError:
            return ""

    # Stat extraction.
    stat_parts: list[str] = []

    npc_type = _param("type")
    environment = _param("environment")
    ai = _param("ai")
    hm = "Hardmode " if _param("hardmode") == "yes" else ""

    type_str = npc_type if npc_type else "NPC"
    stat_parts.append(f"{title} is a {hm}{type_str}.")

    damage_raw = _param("damage")
    if damage_raw:
        if _MODES_RE.search(damage_raw):
            dmg = _extract_modes_first_positional(damage_raw)
        elif not damage_raw.startswith("{{"):
            dmg = re.sub(r"<[^>]+>", "", damage_raw).strip()
        else:
            dmg = None
        if dmg:
            stat_parts.append(f"Damage: {dmg} (Classic mode).")

    defense_raw = _param("defense")
    if defense_raw:
        if _MODES_RE.search(defense_raw):
            dfn = _extract_modes_first_positional(defense_raw)
        elif not defense_raw.startswith("{{"):
            dfn = re.sub(r"<[^>]+>", "", defense_raw).strip()
        else:
            dfn = None
        if dfn:
            stat_parts.append(f"Defense: {dfn}.")

    knockback = _param("knockback")
    if knockback and not knockback.startswith("{{"):
        stat_parts.append(f"Knockback resistance: {knockback}.")

    immune_parts: list[str] = []
    for i in range(1, 10):
        imm = _param(f"immune{i}")
        if imm and not imm.startswith("{{"):
            immune_parts.append(imm)
    if immune_parts:
        stat_parts.append(f"Immune to: {', '.join(immune_parts)}.")

    if environment:
        stat_parts.append(f"Spawns at: {environment}.")
    if ai:
        stat_parts.append(f"AI type: {ai}.")

    if stat_parts:
        results.append(("stats", " ".join(stat_parts)))

    # Drop table synthesis from unnamed infobox params (the drop DSL).
    drop_text = _synthesize_drops(title, box)
    if drop_text:
        results.append(("drops", drop_text))

    return results


# ── Drop table synthesis ──────────────────────────────────────────────────────

_MODE_SUFFIX_RE = re.compile(r"\s*[@#](\w+)\s*$")
_CHANCE_TEMPLATE_RE = re.compile(r"\{\{(?:expert|master)\|([^}]+)\}\}", re.IGNORECASE)


def _clean_chance(raw: str) -> str:
    """Strip mode tags and template wrappers from a chance string."""
    raw = _CHANCE_TEMPLATE_RE.sub(r"\1", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = _MODE_SUFFIX_RE.sub("", raw)
    raw = re.sub(r"\[\[[^\]]+\|([^\]]+)\]\]", r"\1", raw)
    raw = re.sub(r"\[\[([^\]]+)\]\]", r"\1", raw)
    return raw.strip()


def _mode_tag(raw: str) -> str:
    m = _MODE_SUFFIX_RE.search(raw)
    if not m:
        return "all"
    tag = m.group(1).lower()
    if tag == "normal":
        return "normal"
    if tag in ("expert", "master"):
        return tag
    return "all"


def _synthesize_drops(title: str, box: Any) -> str:
    """Parse the NPC infobox's drop DSL and synthesize a readable description."""
    unnamed = [p for p in box.params if not p.showkey]
    values = [str(p.value).strip() for p in unnamed]

    if not values:
        return ""

    # State machine over the unnamed param stream.
    # Triples: item_name, qty, chance_mode_string
    class _State:
        DEFAULT = "default"
        CONDITIONAL = "conditional"
        EXPERT_LOOT = "expert_loot"

    state = _State.DEFAULT
    condition_label = ""
    drops_default: list[str] = []
    drops_by_condition: dict[str, list[str]] = {}
    drops_expert: list[str] = []

    i = 0
    while i < len(values):
        v = values[i]

        if v == ":group:start":
            state = _State.CONDITIONAL
            condition_label = (
                re.sub(r"<[^>]+>", "", values[i + 1]).strip()
                if i + 1 < len(values)
                else "condition"
            )
            # strip source code refs from condition label
            condition_label = re.sub(r"\{\{[^}]+\}\}", "", condition_label).strip()
            i += 2
            continue

        if v == ":group:end" or v.startswith("---"):
            if state == _State.CONDITIONAL:
                state = (
                    _State.EXPERT_LOOT
                    if any(":loot:start" in values[j] for j in range(max(0, i - 20), i))
                    else _State.DEFAULT
                )
                condition_label = ""
            i += 1
            continue

        if v == ":loot:start":
            state = _State.EXPERT_LOOT
            i += 1
            continue

        if v == ":loot:end":
            state = _State.DEFAULT
            i += 1
            continue

        # Skip separator lines.
        if set(v).issubset(set("-|. \t\n")):
            i += 1
            continue

        # Try to read a triple: item_name, qty, chance.
        if i + 2 < len(values):
            raw_name = v
            raw_qty = values[i + 1]
            raw_chance = values[i + 2]

            # A valid triple: qty is a number/range or empty; chance contains %
            # or is a template. Skip if any of these look like control tokens.
            is_control = any(
                x.startswith(":") or x.startswith("---") or x.startswith("-")
                for x in (raw_name, raw_qty, raw_chance)
            )
            has_chance = "%" in raw_chance or "{{" in raw_chance

            if not is_control and has_chance:
                # Handle custom: items — name is after 'custom:'
                if raw_name.startswith("custom:"):
                    item_name = raw_name[len("custom:") :]
                    # The next value is the display template — skip it.
                    # The chance follows.
                    if i + 3 < len(values) and "%" in values[i + 3]:
                        raw_chance = values[i + 3]
                        i += 4
                    else:
                        i += 3
                else:
                    item_name = raw_name
                    i += 3

                item_name = re.sub(r"\{\{[^}]+\}\}", "", item_name).strip()
                qty_str = raw_qty.strip()
                chance = _clean_chance(raw_chance)
                mode = _mode_tag(raw_chance)

                if not item_name or item_name.startswith(":"):
                    continue

                entry = (
                    f"{item_name} ({qty_str}, {chance})"
                    if qty_str
                    else f"{item_name} ({chance})"
                )

                if state == _State.EXPERT_LOOT or mode == "expert":
                    drops_expert.append(entry)
                elif state == _State.CONDITIONAL and condition_label:
                    drops_by_condition.setdefault(condition_label, []).append(entry)
                else:
                    drops_default.append(entry)
                continue

        i += 1

    if not drops_default and not drops_by_condition and not drops_expert:
        return ""

    parts: list[str] = []
    if drops_default:
        parts.append(f"{title} drops: {', '.join(drops_default)}.")
    for cond, items in drops_by_condition.items():
        if items:
            # Truncate long condition labels.
            short_cond = cond[:60]
            parts.append(f"In {short_cond}: {', '.join(items)}.")
    if drops_expert:
        parts.append(f"Expert mode also drops: {', '.join(drops_expert)}.")

    return " ".join(parts)


# ── Sliding-window tokeniser ──────────────────────────────────────────────────


def _token_count(text: str) -> int:
    """Approximate token count: word count × 1.3 (subword inflation factor)."""
    return int(len(text.split()) * 1.3)


def _window(text: str) -> list[str]:
    """Split text into windows respecting the token budget.

    Returns empty list if text is below the minimum token threshold.
    Returns [text] if it fits in one window.
    Returns multiple windows with OVERLAP_TOKENS overlap otherwise.
    """
    if not text:
        return []

    count = _token_count(text)
    if count < _MIN_TOKENS:
        return []
    if count <= _TARGET_TOKENS:
        return [text]

    # Split into words and re-join into windows.
    words = text.split()
    # Approximate words per window.
    words_per_window = max(1, int(_TARGET_TOKENS / 1.3))
    stride = max(1, int((_TARGET_TOKENS - _OVERLAP_TOKENS) / 1.3))

    windows: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + words_per_window, len(words))
        windows.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += stride
    return windows


# ── Section name normalisation ────────────────────────────────────────────────

# Known English section headings on the Terraria wiki (case-insensitive lookup).
# Anything not on this list becomes "misc" so the embed_text prepend stays
# English and the section column in rag_chunks stays low-cardinality.
# The lead section (before any heading) is labelled "intro" by the caller.
_KNOWN_ENGLISH_SECTIONS: frozenset[str] = frozenset(
    {
        "intro",
        "notes",
        "tips",
        "trivia",
        "history",
        "crafting",
        "recipes",
        "used in",
        "crafting tree",
        "obtaining",
        "drops",
        "spawn",
        "spawning",
        "summoning",
        "behavior",
        "mechanics",
        "achievements",
        "see also",
        "references",
        "footnotes",
        "technical info",
        "aftermath",
        "gallery",
        "sound",
        "sounds",
        "strategy",
        "expert mode",
        "master mode",
        "abilities",
        "attacks",
        "defense",
        "equipment",
        "phases",
        "lore",
        "effects",
        "farming",
        "red hat variant",
    }
)


def _normalize_section_name(heading: str) -> str:
    """Return heading if it is a known English section name, else 'misc'.

    Non-ASCII headings (Vietnamese diacritics, CJK, etc.) and ASCII-but-
    unknown headings (e.g. Indonesian "Catatan") are both normalised to
    'misc'.  This caps rag_chunks.section at ~30 distinct values instead of
    1329+ and keeps the embed_text prefix English for every chunk.
    Content is never discarded — only the section label changes.
    """
    if heading.lower().strip() in _KNOWN_ENGLISH_SECTIONS:
        return heading
    return "misc"
