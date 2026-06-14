"""Player-class detection from equipped items (D-009, Phase 3.3).

Hybrid resolution (commit 1 builds the classifier; commit 3 wires it into
``analyze_loadout``):

  item_id → Cargo weapon (if type=weapon)   ← authoritative, ~632 weapons
          → name    → Cargo weapon
          → id→name → curated armor/fallback ← Cargo has NO armor signal (A3)
          → name    → curated armor/fallback
          → None    → (caller may fall back to LLM zero-shot, commit 4)

Two layers:
- **Cargo weapon index** — built at lifespan from ``data/raw/<v>/cargo/items.json``.
  Weapon class comes from the Cargo ``damagetype`` field (``Melee``/``Ranged``/
  ``Magic``/``Summon``, case-normalised), gated on ``type`` containing
  ``"weapon"`` so tools/ammunition that also carry a ``damagetype`` (e.g. a
  pickaxe) are NOT counted (finding A2). Also keeps an id→name bridge for all
  items so an armor ``item_id`` from the mod can reach the curated map.
- **Curated map** — the demoted Phase 3.2 hardcoded dict. It survives because
  (A3) Cargo carries no armor class data, and (A4) ``data/raw/`` is gitignored
  so CI has no Cargo file — the module-level ``DEFAULT_CLASSIFIER`` is
  curated-only and is what unit tests resolve against. Production injects a
  Cargo-backed ``ItemClassifier`` (cached on ``app.state.item_classifier``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.domain.bot import StatePayload
from app.infra.anthropic import AnthropicClient, ChatMessage

_FALLBACK_MODEL = "claude-haiku-4-5"
_VALID_CLASSES: frozenset[str] = frozenset({"melee", "ranger", "mage", "summoner"})

# Cargo damagetype (lowercased) → canonical class name.
_DAMAGETYPE_TO_CLASS: dict[str, str] = {
    "melee": "melee",
    "ranged": "ranger",
    "magic": "mage",
    "summon": "summoner",
}

# ── Curated item → class map (demoted Phase 3.2 dict) ─────────────────────────
# Kept (not deleted) because Cargo has no armor class signal (A3) and the Cargo
# file is gitignored, so CI relies on this map (A4). Keyed by name.lower().
CURATED_ITEM_CLASS: dict[str, str] = {
    # Melee armor
    "shadow helmet": "melee",
    "shadow scalemail": "melee",
    "shadow greaves": "melee",
    "crimson helmet": "melee",
    "crimson scalemail": "melee",
    "crimson greaves": "melee",
    "molten helmet": "melee",
    "molten breastplate": "melee",
    "molten greaves": "melee",
    "cobalt helmet": "melee",
    "cobalt breastplate": "melee",
    "cobalt leggings": "melee",
    "mythril helmet": "melee",
    "hallowed mask": "melee",
    "hallowed plate mail": "melee",
    "hallowed greaves": "melee",
    "chlorophyte mask": "melee",
    # Melee weapons
    "copper shortsword": "melee",
    "iron shortsword": "melee",
    "gold broadsword": "melee",
    "platinum broadsword": "melee",
    "fiery greatsword": "melee",
    "nights edge": "melee",
    "night's edge": "melee",
    "terra blade": "melee",
    "excalibur": "melee",
    "influx waver": "melee",
    # Ranger armor
    "jungle shirt": "ranger",
    "jungle pants": "ranger",
    "fossil helmet": "ranger",
    "fossil plate": "ranger",
    "fossil greaves": "ranger",
    "cobalt hat": "ranger",
    "mythril hat": "ranger",
    "hallowed headgear": "ranger",
    "chlorophyte helmet": "ranger",
    # Ranger weapons
    "musket": "ranger",
    "the undertaker": "ranger",
    "boomstick": "ranger",
    "molten fury": "ranger",
    "phoenix blaster": "ranger",
    "megashark": "ranger",
    "uzi": "ranger",
    "chlorophyte shotbow": "ranger",
    "sdmg": "ranger",
    "s.d.m.g.": "ranger",
    # Mage armor
    "meteor helmet": "mage",
    "meteor suit": "mage",
    "meteor leggings": "mage",
    "wizard hat": "mage",
    "jungle hat": "mage",
    "spectre mask": "mage",
    "spectre hood": "mage",
    "spectre robe": "mage",
    "spectre pants": "mage",
    "chlorophyte headgear": "mage",
    # Mage weapons
    "space gun": "mage",
    "water bolt": "mage",
    "magic missile": "mage",
    "demon scythe": "mage",
    "crystal storm": "mage",
    "golden shower": "mage",
    "razorblade typhoon": "mage",
    "last prism": "mage",
    # Summoner armor
    "bee helmet": "summoner",
    "bee breastplate": "summoner",
    "bee greaves": "summoner",
    "spider mask": "summoner",
    "spider breastplate": "summoner",
    "spider greaves": "summoner",
    "tiki mask": "summoner",
    "tiki shirt": "summoner",
    "tiki pants": "summoner",
    # Summoner weapons
    "imp staff": "summoner",
    "hornet staff": "summoner",
    "spider staff": "summoner",
    "optic staff": "summoner",
    "raven staff": "summoner",
}


def _norm_name(name: str) -> str:
    """Normalise an item name for lookup: strip + lowercase (spaces preserved)."""
    return name.strip().lower()


def _is_weapon_type(type_field: str) -> bool:
    """True if the Cargo ``type`` has a ``weapon`` segment (finding A2).

    ``type`` is a ``^``-joined multi-tag (e.g. ``"weapon^crafting material"``,
    Minishark's shape), while the class signal ``damagetype`` is always clean.
    Splitting on ``^`` makes the multi-tag handling explicit and excludes
    tools/ammunition/furniture that carry a ``damagetype`` or contain "weapon"
    as a substring (e.g. a "weapon rack"). Behaviour-identical on real 1.4.4.9
    data to the prior substring check (445 weapon item_ids either way).
    """
    return "weapon" in {seg.strip() for seg in type_field.lower().split("^")}


class ItemClassifier:
    """Resolves a Terraria item (by ``item_id`` or ``name``) to a class.

    Construct directly for unit tests, or via :meth:`from_cargo_file` at
    lifespan. The curated layer is always present; the Cargo layer is empty
    unless built from a Cargo file (the curated-only ``DEFAULT_CLASSIFIER``).
    """

    def __init__(
        self,
        *,
        curated: dict[str, str] | None = None,
        cargo_weapon_by_id: dict[int, str] | None = None,
        cargo_weapon_by_name: dict[str, str] | None = None,
        cargo_name_by_id: dict[int, str] | None = None,
        cargo_item_count: int = 0,
    ) -> None:
        self._curated = curated if curated is not None else CURATED_ITEM_CLASS
        self._cargo_weapon_by_id = cargo_weapon_by_id or {}
        self._cargo_weapon_by_name = cargo_weapon_by_name or {}
        self._cargo_name_by_id = cargo_name_by_id or {}
        self.cargo_item_count = cargo_item_count

    @property
    def cargo_weapon_count(self) -> int:
        return len(self._cargo_weapon_by_id)

    def classify(self, *, item_id: int = 0, name: str = "") -> str | None:
        """Return the class for an item, or ``None`` if no signal.

        Resolution order (item_id wins over name; Cargo weapon wins over the
        curated armor/fallback map):
          1. item_id → Cargo weapon
          2. name    → Cargo weapon
          3. item_id → Cargo name → curated  (armor bridge for mod item_ids)
          4. name    → curated
        """
        if item_id and item_id in self._cargo_weapon_by_id:
            return self._cargo_weapon_by_id[item_id]

        nkey = _norm_name(name)
        if nkey and nkey in self._cargo_weapon_by_name:
            return self._cargo_weapon_by_name[nkey]

        if item_id and item_id in self._cargo_name_by_id:
            cargo_name = _norm_name(self._cargo_name_by_id[item_id])
            if cargo_name in self._curated:
                return self._curated[cargo_name]

        if nkey and nkey in self._curated:
            return self._curated[nkey]

        return None

    @classmethod
    def from_cargo_file(
        cls,
        path: str | Path,
        *,
        min_items: int = 100,
    ) -> ItemClassifier:
        """Build a Cargo-backed classifier from a Cargo ``items.json`` file.

        Refuses to boot (raises ``RuntimeError``) when the file is missing,
        unparseable, not a JSON array, or has fewer than ``min_items`` rows
        (a truncation sanity check — the real 1.4.4.9 table has 6,233 rows).
        """
        p = Path(path)
        if not p.exists():
            raise RuntimeError(
                f"REFUSING TO BOOT: Cargo items file missing — {p}. "
                "Run scripts/scrape_cargo.py to populate data/raw/<version>/cargo/."
            )
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(
                f"REFUSING TO BOOT: Cargo items file unparseable — {p}: {exc}"
            ) from exc
        if not isinstance(data, list):
            raise RuntimeError(
                f"REFUSING TO BOOT: Cargo items file is not a JSON array — {p}"
            )
        if len(data) < min_items:
            raise RuntimeError(
                f"REFUSING TO BOOT: Cargo items file {p} has only {len(data)} rows "
                f"(need ≥ {min_items}) — data looks truncated"
            )

        weapon_by_id: dict[int, str] = {}
        weapon_by_name: dict[str, str] = {}
        name_by_id: dict[int, str] = {}

        for row in data:
            if not isinstance(row, dict):
                continue
            raw_id = str(row.get("itemid", "")).strip()
            item_id = int(raw_id) if raw_id.isdigit() else 0
            name = str(row.get("name", ""))
            nkey = _norm_name(name)

            if item_id and name:
                name_by_id[item_id] = name

            # Gate on a "weapon" segment of `type` so tools/ammunition that carry
            # a damagetype (e.g. pickaxes, bullets) are not counted (finding A2).
            if _is_weapon_type(str(row.get("type", ""))):
                dt = str(row.get("damagetype", "")).strip().lower()
                cls_name = _DAMAGETYPE_TO_CLASS.get(dt)
                if cls_name:
                    if item_id:
                        weapon_by_id[item_id] = cls_name
                    if nkey:
                        weapon_by_name[nkey] = cls_name

        return cls(
            cargo_weapon_by_id=weapon_by_id,
            cargo_weapon_by_name=weapon_by_name,
            cargo_name_by_id=name_by_id,
            cargo_item_count=len(data),
        )


# Curated-only, CI-safe default (no Cargo data). Production overrides this with
# a Cargo-backed instance on app.state.item_classifier (lifespan).
DEFAULT_CLASSIFIER = ItemClassifier()


# ── LLM zero-shot cold-start fallback (D-009) ─────────────────────────────────
# Fires from the agent graph's execute_tools node (NOT from analyze_loadout,
# which must keep returning class=None for empty/unknown gear) when the
# deterministic classifier finds no signal. ~$0.0002/call (80 in / 8 out at
# Haiku pricing), cold-start path only.


def _summarize_loadout(state: StatePayload) -> str:
    """Compact name-based summary of the player's gear + inventory for the LLM."""

    def names(items: list[Any]) -> list[str]:
        return [i.name for i in items if i.name]

    armor = names(state.gear.armor)
    accessories = names(state.gear.accessories)
    inventory = names(state.inventory)
    weapon = (
        state.gear.weapon.name
        if state.gear.weapon and state.gear.weapon.name
        else "(none)"
    )
    return (
        f"Equipped armor: {', '.join(armor) if armor else '(none)'}\n"
        f"Weapon: {weapon}\n"
        f"Accessories: {', '.join(accessories) if accessories else '(none)'}\n"
        f"Inventory: {', '.join(inventory) if inventory else '(none)'}"
    )


def _parse_class_reply(reply: str) -> str | None:
    """Return the first recognized class keyword in *reply*, else None.

    The model is asked for one word, but ``max_tokens=8`` does not guarantee a
    clean reply. The rule is: scan the lowercased reply's word tokens and return
    the first that is one of the four classes; anything else (including
    "unknown" or off-vocabulary text) yields None.
    """
    tokens: list[str] = re.findall(r"[a-z]+", reply.lower())
    for token in tokens:
        if token in _VALID_CLASSES:
            return token
    return None


async def llm_classify(
    state: StatePayload,
    *,
    anthropic: AnthropicClient,
    prompt: str,
    parent_span: Any = None,
) -> dict[str, Any]:
    """Infer the player's class from gear + inventory via a one-word LLM call.

    Returns ``{"class": <class>, "confidence": "llm-zero-shot"}`` on a
    recognized reply, else ``{"class": None, "confidence":
    "llm-zero-shot-unknown"}``.
    """
    messages: list[ChatMessage] = [
        {"role": "user", "content": _summarize_loadout(state)}
    ]
    reply, _, _ = await anthropic.chat(
        messages=messages,
        model=_FALLBACK_MODEL,
        system=prompt,
        max_tokens=8,
        span_name="agent.llm_classify",
        parent=parent_span,
    )
    cls = _parse_class_reply(reply)
    if cls is not None:
        return {"class": cls, "confidence": "llm-zero-shot"}
    return {"class": None, "confidence": "llm-zero-shot-unknown"}
