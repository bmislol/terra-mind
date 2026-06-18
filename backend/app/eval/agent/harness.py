"""Agent live-state grounding measurement (Phase 6.3 — P-016 broad measurement).

Closes the 4.4 boundary: the `agent_system.md` grounding fix was proven n≈5
in-game; this measures whether it **generalizes**. The agent reaches the live
`StatePayload` ONLY by calling a live-state tool (`analyze_loadout` /
`suggest_next_boss`) — the 4.4 finding — so a tool call is the **objective**
proxy for "grounded in live state", no judge needed.

**Metric:** grounding rate = fraction of progression questions where the agent
called a live-state tool. Plus a melee↔ranger **distinctness** spot-check (same
question, two class states → class-appropriate answers).

A **measured number, not a CI gate** (LLM- + corpus-dependent). Run:
    DATABASE_URL=... ANTHROPIC_API_KEY=... uv run python -m app.eval.agent.harness
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from anthropic.types import TextBlock, ToolUseBlock
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent.class_detection import ItemClassifier
from app.agent.graph import build_agent_graph
from app.core.lifespan import _load_prompts
from app.db.session import make_session_factory
from app.domain.bot import StatePayload
from app.infra.anthropic import AnthropicClient
from app.rag.embedder import Embedder
from app.rag.pipeline import RetrievalPipeline

_BACKEND_ROOT = Path(__file__).parents[3]
_QUESTION_SET = _BACKEND_ROOT / "data" / "eval" / "agent_grounding.jsonl"
_PROMPTS_DIR = _BACKEND_ROOT / "app" / "prompts"
_CARGO_ITEMS = _BACKEND_ROOT / "data" / "raw" / "1.4.4.9" / "cargo" / "items.json"

#: Tools that read the live StatePayload (vs query_wiki, which doesn't).
_LIVE_STATE_TOOLS = {"analyze_loadout", "suggest_next_boss"}

_RANGED_TERMS = ("bow", "gun", "arrow", "bullet", "ranged", "ranger", "minishark")
_MELEE_TERMS = ("sword", "melee", "spear", "yoyo", "broadsword", "shortsword")


def _tools_called(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for msg in messages:
        content = msg.get("content", [])
        if isinstance(content, list):
            names.extend(b.name for b in content if isinstance(b, ToolUseBlock))
    return names


def _final_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, TextBlock):
                    return block.text
    return ""


async def _run(graph: Any, question: str, state: StatePayload) -> tuple[list[str], str]:
    result = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": question}],
            "chunks_seen": [],
            "iteration_count": 0,
            "state_payload": state,
        }
    )
    msgs = result["messages"]
    return _tools_called(msgs), _final_text(msgs)


def _build_graph() -> Any:
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not db_url or not api_key:
        sys.exit("ERROR: DATABASE_URL + ANTHROPIC_API_KEY are required")
    engine = create_async_engine(db_url, pool_pre_ping=True)
    retrieval = RetrievalPipeline(
        session_factory=make_session_factory(engine), embedder=Embedder()
    )
    anthropic = AnthropicClient(api_key=api_key)
    prompts = _load_prompts(_PROMPTS_DIR)
    classifier = ItemClassifier.from_cargo_file(str(_CARGO_ITEMS))
    return build_agent_graph(retrieval, anthropic, prompts, classifier)


async def run_harness() -> dict[str, Any]:
    if not _QUESTION_SET.exists():
        sys.exit(f"ERROR: question set not found at {_QUESTION_SET}")
    records = [
        json.loads(line)
        for line in _QUESTION_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    graph = _build_graph()

    per_q: list[dict[str, Any]] = []
    grounded = 0
    for r in records:
        state = StatePayload.model_validate(r["state"])
        tools, answer = await _run(graph, r["question"], state)
        is_grounded = any(t in _LIVE_STATE_TOOLS for t in tools)
        grounded += int(is_grounded)
        per_q.append(
            {
                "question": r["question"],
                "class": r["class"],
                "stage": r["stage"],
                "tools": tools,
                "grounded": is_grounded,
                "answer": answer[:240],
            }
        )

    # Distinctness spot-check: one fixed question, two class states.
    spot_q = "What weapon should I focus on upgrading next?"
    melee_state = StatePayload.model_validate(records[0]["state"])  # a melee record
    ranger_rec = next(r for r in records if r["class"] == "ranger")
    ranger_state = StatePayload.model_validate(ranger_rec["state"])
    _, melee_ans = await _run(graph, spot_q, melee_state)
    _, ranger_ans = await _run(graph, spot_q, ranger_state)
    spot = {
        "question": spot_q,
        "melee_answer": melee_ans[:240],
        "ranger_answer": ranger_ans[:240],
        "melee_mentions_melee": any(t in melee_ans.lower() for t in _MELEE_TERMS),
        "ranger_mentions_ranged": any(t in ranger_ans.lower() for t in _RANGED_TERMS),
        "answers_differ": melee_ans.strip() != ranger_ans.strip(),
    }

    n = len(records)
    return {
        "n": n,
        "grounded": grounded,
        "rate": round(grounded / n, 3),
        "per_q": per_q,
        "spot_check": spot,
    }


def print_report(report: dict[str, Any]) -> None:
    print("\n── Agent grounding (live-state tool call per question) ──────")
    for q in report["per_q"]:
        mark = "✓" if q["grounded"] else "·"
        live = [t for t in q["tools"] if t in _LIVE_STATE_TOOLS]
        print(
            f"  {mark} [{q['class'][:6]:6}/{q['stage'][:14]:14}] "
            f"tools={q['tools']} live={live or '—'}  {q['question'][:50]}"
        )
    print(
        f"\n  GROUNDING RATE: {report['grounded']}/{report['n']} = {report['rate']:.0%}"
    )
    s = report["spot_check"]
    print("\n── Melee↔ranger distinctness spot-check ─────────────────────")
    print(f"  Q: {s['question']}   (answers differ: {s['answers_differ']})")
    print(f"  melee  [melee-terms={s['melee_mentions_melee']}]:")
    print(f"    {s['melee_answer']}")
    print(f"  ranger [ranged-terms={s['ranger_mentions_ranged']}]:")
    print(f"    {s['ranger_answer']}")
    print()


async def _main() -> None:
    report = await run_harness()
    print_report(report)


if __name__ == "__main__":
    asyncio.run(_main())
