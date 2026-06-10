# Checklist.md

Granular, phase-by-phase progress tracker for **terra-mind**. This file is the single source of truth for *what to build next*. It is **expanded as we go**: near-term phases carry full closeout checklists; later phases are outlines that get fleshed out when reached.

**Conventions** (per D-015)
- One phase = one branch `feat/<NN>-<slug>` = one PR = CI green = squash merge = tick the phase.
- Conventional commits. Update the relevant `deliverables/` file in the **same PR** as the code.
- Don't bleed scope across phases; if new scope appears, open a new branch or log a deferral in `DECISIONS.md`.
- `CLAUDE.md §2` mirrors the current section/phase; update it when a phase closes.

**Status legend:** `[ ]` todo · `[~]` in progress · `[x]` done

**Loose day mapping** (target delivery 2026-06-18; buffer 17–18):
S1 Days 1–2 · S2 Days 3–5 · S3 Days 5–7 · S4 Days 7–9 · S5 Days 9–11 · S6 Days 11–12 · S7 Days 13–14.

> **Already drafted (pre-Phase-1.1):** `deliverables/DECISIONS.md` (D-001…D-016 + Pending P-001…P-008) and `deliverables/ARCH.md`. These get committed in Phase 1.1.

---

## Section 1 — Foundations & Spike (Days 1–2)

Goal: a reproducible skeleton that boots clean from a fresh clone, with the riskiest unknown (the tModLoader bridge) proven on day one.

### Phase 1.1 · Repo skeleton & Git hygiene — `feat/01-foundations`
- [x] Finalize `.gitignore` (Python base + Node + .NET/tModLoader + `.personal/` + data volumes). Verify `git check-ignore .personal/<file>` returns the path.
- [x] `.gitkeep` in every empty folder of the §3 layout.
- [x] `.github/pull_request_template.md` (adapted — see note below).
- [x] `CONTRIBUTING.md` at root.
- [x] Root `README.md` (stub; expanded later).
- [x] Commit drafted `deliverables/DECISIONS.md` and `deliverables/ARCH.md`.
- [x] Create empty `deliverables/{RUNBOOK,EVALS,SECURITY,LICENSES}.md` stubs.
- [x] `eval_thresholds.yaml` created with placeholder keys (values `PENDING`, filled in S2/S6).
- [x] Branch protection on `main` configured in GitHub UI.
- [x] All on `feat/01-foundations`; PR via template; squash merge; tick 1.1.

### Phase 1.2 · tModLoader spike — `feat/02-tmodloader-spike`
> Riskiest unknown first. Throwaway — proves the bridge, not a feature.
- [x] Confirm tModLoader → Develop Mods detects the .NET 8 SDK (the one tonight's check covered).
- [x] Minimal mod: read current HP from `Main.LocalPlayer`.
- [x] Async `HttpClient` POST to a local FastAPI echo stub; print reply via `Main.NewText`.
- [x] Round-trip works in singleplayer without freezing the game thread.
- [x] Note findings (SDK quirks, API signatures) in `RUNBOOK.md`; tick 1.2.

### Phase 1.3 · Python tooling & FastAPI skeleton — `feat/03-python-tooling`
- [x] `backend/app/` package tree per `ARCH.md §3` with `__init__.py`.
- [x] `backend/pyproject.toml` (FastAPI, uvicorn, ruff, mypy, pytest) via `uv`; commit `uv.lock`.
- [x] `app/main.py` with `/healthz`.
- [x] `tests/test_healthz.py`.
- [x] `.github/workflows/ci.yml` (lint/format/type-check/test).
- [x] Local CI green; PR; CI green on PR; enable "Require status checks" on `main`; merge; tick 1.3.

### Phase 1.4 · Compose skeleton — `feat/04-compose-skeleton`
- [x] `backend/Dockerfile`.
- [x] `docker-compose.yml`: `db` (pgvector/pg16), `redis`, `vault`, `vault-init`, `langfuse`, `migrate`, `api`, `frontend-admin` + `frontend-user` stubs. (No minio/modelserver/widget/host — D-014, D-009, D-011.)
- [x] `.env.example` with all non-secret config + secret placeholders.
- [x] `docker compose up --build` → every service healthy; each `/healthz` 200.
- [x] `down -v && up --build` → clean fresh boot second time.
- [x] `RUNBOOK.md §1` (startup) + `ARCH.md §2` sanity-checked; tick 1.4.

### Phase 1.5 · Vault + Alembic + RLS scaffolding — `feat/05-vault-alembic-rls`
- [x] `app/core/config.py`, `app/core/lifespan.py`, `app/infra/vault.py`.
- [x] `scripts/vault-init.sh`; seeds `anthropic.api_key`, `jwt.signing_key`.
- [x] Refuse-to-boot if Vault unreachable; `tests/test_refuse_to_boot.py`.
- [x] ORM models: `tenants`, `sessions`, `messages`, `rag_chunks`, `audit_log` (no `memory_long` — D-010).
- [x] Alembic init (async); first migration; `CREATE EXTENSION vector` added; **RLS policies** on tenant-scoped tables.
- [x] `down -v && up --build`: vault-init seeds, migrate runs, tables + `vector` ext present; RLS verified (Tenant A can't read Tenant B).
- [x] `ARCH.md §6/§9`, `SECURITY.md`; tick 1.5.

### Phase 1.6 · Langfuse + logging + redaction stub — `feat/06-langfuse-logging`
- [x] `app/core/logging.py` (JSON), `app/infra/tracing.py`, `app/api/middleware.py` (request_id/trace_id/tenant_id contextvars).
- [x] Refuse-to-boot if Langfuse unreachable.
- [x] `/healthz` returns `X-Request-ID`; logs are structured JSON; trace visible in Langfuse UI.
- [x] `app/infra/redaction.py` stub + `tests/test_logging.py` + redaction test.
- [x] `ARCH.md §12`, `DECISIONS` (Langfuse config); tick 1.6.

---

## Section 2 — Corpus & RAG (Days 3–5)

Goal: a version-tagged wiki corpus in pgvector and a measured dense-retrieval baseline. Write the golden set **early** so it can't be skipped.

### Phase 2.1 · Wiki scrape — `feat/07-wiki-scrape`
- [x] Confirm target Terraria version = tModLoader stable's supported version (D-016); record it.
- [x] `scripts/scrape_wiki.py`: MediaWiki API, rate-limited, resumable cache → `data/raw/<version>/`.
- [x] `manifest.json` with `raw_sha256`, page count, source, scraped_at.
- [x] Attribution + license recorded in `LICENSES.md`; `ARCH.md §10`; tick.

### Phase 2.2 · Chunk + embed + corpus build — `feat/08-corpus-build`

#### Scripts
#### Scripts
- [x] `scripts/scrape_cargo.py` — cargoquery pagination (Items + Recipes tables), rate-limited, idempotent, atomic writes, loud failure on any error.
- [x] `scripts/_cargo/__init__.py`, `_cargo/fetcher.py` (cargoquery loop, retry), `_cargo/manifest.py` (cargo_raw_sha256, manifest merge).
- [x] `scripts/build_corpus.py` — loads Cargo dicts at startup, reads pages/, chunks+embeds+upserts into `rag_chunks`, writes manifest cargo fields.

#### app/rag/
- [x] `app/rag/models.py` — `ChunkRecord` Pydantic model.
- [x] `app/rag/chunker.py` — all chunk types: Cargo stats, recipe, NPC template synthesis, prose sections (structural + sliding window), mwparserfromhell wikitext stripping.
- [x] `app/rag/embedder.py` — `SentenceTransformer` wrapper, batch encode, returns `np.ndarray` of shape `(n, 384)`.

#### ORM + migration
- [x] `app/db/models.py` — add `page_id`, `chunk_index`, `revision_id`, `source_url` fields to `RagChunk`.
- [x] New Alembic migration — 4 columns + `UNIQUE (page_id, chunk_index, game_version)` constraint + HNSW index `(embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`.

#### Dependencies
- [x] `pyproject.toml` — add `mwparserfromhell`, `sentence-transformers`, `psycopg[binary]` to runtime deps; add mypy `ignore_missing_imports` overrides for new packages.
- [x] `uv lock && uv sync` after dep changes; confirm `uv.lock` committed.

#### Tests (87 total after all cleanup fixes — ruff + mypy + pytest all green, no live network or DB)
- [x] `tests/rag/__init__.py` + `tests/rag/test_chunker.py` — chunker tests covering prose chunking, disambiguation filter, token budget, template synthesis, Cargo stats synthesis, HTML stripping, broken-bar recipe parsing, multi-recipe chunks, orphan recipe logging, Cargo-item-without-wiki-page skip, section normalisation.
- [x] `tests/rag/test_embedder.py` — 4 tests: correct output shape, batching, L2-normalised vectors, empty input.
- [x] `tests/scripts/test_scrape_cargo.py` — unit tests for `_cargo/` (pagination parse, field handling, manifest merge, failure policy).
- [x] `tests/scripts/test_build_corpus.py` — upsert SQL regression guard + SQLite integration test; orphan write tests.

#### Deliverables (updated in same PR, before manual runs)
- [x] `deliverables/ARCH.md §10` — add `scrape_cargo.py` to offline pipeline diagram; document `cargo/` output layout and `manifest.json` `cargo_*` field extensions.
- [x] `deliverables/ARCH.md §11` — corpus stats table updated with measured values (22,173 chunks, 29 sections, HNSW index confirmed).
- [x] `deliverables/DECISIONS.md` — graduate P-001 → D-018 and P-002 → D-019 with final measured numbers; revision log entries.
- [x] `deliverables/LICENSES.md §2` — confirm Cargo data carries same CC BY-NC-SA 4.0 as wikitext (same wiki, same content).
- [x] `deliverables/RUNBOOK.md §4` — invocation sequence: `scrape_wiki` → `scrape_cargo` → `build_corpus`.
- [x] `CLAUDE.md §2` status line updated (last, after operator verifies and ticks all items above).

#### Manual verification (operator runs after CI green — not part of agent gate)
- [x] `scrape_cargo.py --version 1.4.4.9` runs end-to-end; `cargo/items.json` (6,233 rows) and `cargo/recipes.json` (4,221 rows) present; `manifest.json` has valid `cargo_raw_sha256` and `cargo_table_counts`; idempotent re-run exits cleanly.
- [x] `build_corpus.py --version 1.4.4.9` runs end-to-end; 22,173 chunks in `rag_chunks`; manifest updated with `chunk_count=22173`, `embedding_model`, `embedding_dim`.
- [x] Stats spot-check: Megashark, Wooden Sword, Last Prism each have a `section="stats"` chunk with correct `damage` and `usetime` from Cargo.
- [x] Recipe spot-check: two multi-recipe items each have one `section="recipe"` chunk per recipe with correct ingredients (broken-bar parsing verified).

### Phase 2.3 · RAG golden set — `feat/09-rag-golden`
- [x] 15 Terraria progression questions + expected source chunks → `data/eval/eval_rag.jsonl`.
- [x] Spot-check answers exist in the corpus; `EVALS.md` documents the set; tick.

### Phase 2.4 · Dense retrieval + hit@k — `feat/10-rag-dense`
- [x] `app/rag/pipeline.py`: dense-only, `game_version`-filtered (D-008).
- [x] Eval harness (`app/eval/rag/harness.py`); measure hit@k baseline → set thresholds in `eval_thresholds.yaml` (graduate P-003 → D-020).
- [x] `.github/workflows/eval-rag.yml` (manual dispatch; needs live DB).
- [x] Decide hybrid escalation from the number (P-007): hit@5=0.667 < 0.75 → P-007 stays OPEN, forcing function documented in `DECISIONS.md`; `ARCH.md §11`, `EVALS.md §1.5–1.6` updated; tick.

### Phase 2.5 · Deterministic chunk IDs + harness fixes — `feat/11-eval-robustness`
> Discovered during Phase 2.4 closeout: `rag_chunks.id` is a random UUID4 generated at insert time. After `docker compose down -v` the corpus rebuilds with new UUIDs, silently invalidating the golden set. This phase hardens the eval pipeline so it survives a volume wipe.
- [x] **Deterministic chunk IDs** — `app/rag/chunker.py`: add `chunk_id(page_id, chunk_index, game_version)` helper using `uuid5(NAMESPACE_OID, …)`. `build_corpus.py`: replace `uuid4()` with `chunk_id(…)`. IDs are now content-addressed; a volume wipe followed by rebuild produces identical UUIDs (D-021).
- ~~**Schema migration**~~ — *struck; incorrect. The application supplies `id` explicitly on every INSERT; there is no DB DEFAULT to change. TRUNCATE + rebuild is the correct reset procedure — no Alembic migration needed.*
- [x] **Corpus rebuild** — `docker compose down -v && up --build`, then `build_corpus.py --version 1.4.4.9`; chunk count confirmed 22,173 exactly (STEP 3 + STEP 6).
- [x] **Rewrite `eval_rag.jsonl`** with the deterministic UUIDs via `scripts/refresh_golden_set.py` (run once against the pre-rebuild DB). All 35 UUIDs resolve in the new DB (STEP 4).
- [x] **Threshold direction fix** — `app/core/threshold_directions.py` (shared helper, D-022); `harness.py` `_assert_thresholds` delegates to `passes_threshold(key, measured, threshold)`. `_max` keys now correctly fail when `measured > threshold`; `_min` keys fail when `measured < threshold`.
- [x] **Refuse-to-boot on zero thresholds** — `app/core/lifespan.py` `_walk_thresholds`: tightened using `zero_is_valid_for_key(leaf_key)` from the shared helper. `rag.*_min: 0` and `rag.*_max: 0` now refuse to boot; `redteam.max_successful_injections: 0` still passes.
- [x] **Unit tests** — `tests/rag/test_chunker.py` (3 deterministic-ID tests); `tests/eval/rag/test_harness.py` (11 tests: `passes_threshold` + `_assert_thresholds` integration); `tests/scripts/test_refresh_golden_set.py` (8 tests); `tests/test_refuse_to_boot.py` (2 new refuse-on-zero tests).
- [x] **Re-run eval harness** after rebuild; hit@5 = 0.667 exactly; exit code 0; threshold checks all pass including `p95_latency_ms_max` (STEP 5 + STEP 6). Per-question pattern identical to Phase 2.4 baseline.
- [x] **Deliverables** — `DECISIONS.md` D-021 + D-022 added; `EVALS.md §1.7` (golden-set stability guarantee + threshold direction fix); `RUNBOOK.md §4 + §6` (deterministic IDs, refresh script, post-wipe guarantee); `Checklist.md` ticked; `CLAUDE.md §2` updated.
- [x] Mock embedder in unit tests (tests/rag/test_pipeline.py).
      Currently the test instantiates a real SentenceTransformer which
      blocks CI on HuggingFace Hub download/rate-limits. CI runs hung
      for 13+ minutes on PR #26 because of this. Add a pytest fixture
      that returns a deterministic 384-dim numpy array.

---

## Section 3 — Router, Agent & Class Detection (Days 5–7)

Goal: the FastAPI backend produces real answers. The retrieval pipeline
from Phase 2.4 becomes useful via a router that picks between deterministic
RAG and an agent that calls tools. Class detection from live game state
is the third leg. This is the first section that calls Anthropic's API,
so every phase has real per-token costs.

**Pre-section flight check (do before starting Phase 3.1):**
- [ ] Anthropic API key is real, not the placeholder. Set
      `ANTHROPIC_API_KEY=sk-ant-...` in `.env` (gitignored). Confirm
      Vault picks it up at boot: `docker compose exec api env | grep -i
      anthropic` shows the real value masked, NOT the placeholder string.
- [ ] First-call smoke test from inside the api container:
      `docker compose exec api uv run python -c "from anthropic import
      Anthropic; print(Anthropic().models.list().data[0].id)"` — should
      print a model ID without erroring.
- [ ] Set a usage cap in your Anthropic console before Section 3 starts.
      Suggested: $20 for the whole section. If you hit the cap, something
      is wrong with the agent's loop, not the cap.
- [ ] Confirm Langfuse can record an LLM generation (not just spans):
      Section 2.4 only opened spans; Section 3 records `generation` events
      with model name, input tokens, output tokens. The Langfuse Python
      SDK's `trace.generation(...)` API. Verify in Phase 3.1 below.

---

### Phase 3.1 · Classifier router + `/bot/ask` endpoint — `feat/12-router`

**Goal:** First end-to-end answer. The `/bot/ask` endpoint accepts a
question + state payload, classifies it into one of two paths (easy FAQ
→ deterministic RAG; hard state-dependent → agent stub), routes
accordingly, and returns a single JSON reply. The agent path is a stub
here (returns "agent not yet implemented"); 3.2 fills it in. Both paths
exercise a full Langfuse trace tree.

**This phase is bigger than its outline suggested** — it's the first
real Anthropic call, the first `/bot/ask` endpoint, the first router
prompt, and the first end-to-end trace. Treat it as the foundation for
3.2 and 3.3.

#### Closeout
- [ ] Endpoint scaffolding: `app/api/bot.py` with `POST /bot/ask`.
      Request body schema: `{message: str, state: StatePayload | None}`.
      `StatePayload` is a Pydantic model from `app/domain/` matching
      ARCH.md §5 step 1 (gear, inventory, hardmode, downed bosses,
      biome, game_version). For Phase 3.1 it can be optional/stub —
      the router doesn't use it yet.
- [ ] Router prompt: `app/prompts/router.md`. System prompt + few-shot
      examples that classify the user's question into `"faq"` (single
      lookup; "Megashark damage" "Wooden Sword recipe") or `"agent"`
      (multi-step, state-dependent; "why do I keep dying to Skeletron",
      "what should I do next"). Versioned prompt file, loaded at runtime.
- [ ] Router service: `app/services/router.py`. Single LLM call to
      `claude-haiku-4-5` (D-003) with the router prompt + user question.
      Parses the classification result. **No state payload in the
      router prompt** — the router just decides the path, doesn't
      consume state. Returns a `RoutingDecision` enum.
- [ ] FAQ path: when router returns "faq", call the
      `RetrievalPipeline.retrieve()` from Phase 2.4 with the user
      question + `game_version` from state (default to `"1.4.4.9"`
      if state is absent), top-1 chunk. **Single LLM call to
      synthesize an answer from the chunk** — this is where the user
      actually gets a response. Prompt template:
      `app/prompts/faq_answer.md`. Model: claude-haiku-4-5. Returns
      `{answer: str, source_chunks: list[ChunkRef]}`.
- [ ] Agent path stub: when router returns "agent", return a placeholder
      `{answer: "I need more analysis — agent path coming in Phase 3.2",
      source_chunks: []}`. The path is exercised by tests but Section
      3.2 fills it in.
- [ ] Anthropic SDK integration: `app/infra/anthropic.py`. Async client
      loaded at lifespan startup, key from Vault. Wraps the SDK with
      Langfuse generation tracing — every LLM call must emit a
      `trace.generation()` event with `model`, `input`, `output`,
      `input_tokens`, `output_tokens` so the cost trail is visible.
- [ ] Langfuse trace tree (the graded "traces are real" check): one
      trace per `/bot/ask` request. Spans: `router.classify`,
      `rag.retrieve` (already from 2.4), `faq.synthesize` or
      `agent.stub`. Each LLM call is a `generation` event under the
      relevant span. Verify in the Langfuse UI by sending two
      questions (one of each path) and inspecting both traces.
- [ ] Unit tests: `tests/services/test_router.py` with mock Anthropic.
      Cover both routing decisions, malformed LLM output handling, and
      timeout behavior. `tests/api/test_bot_ask.py` exercises the
      endpoint end-to-end with mocked LLM calls.
- [ ] Integration test (manual, not in CI): send a real `/bot/ask`
      request with `{message: "What does Megashark damage?", state:
      null}` and confirm a coherent answer with `damage: 25` in it.
      Send `{message: "Why do I keep dying to Skeletron?"}` and confirm
      the agent-stub response.
- [ ] DECISIONS.md: Lock the router model choice with rationale.
      Likely D-023 — claude-haiku-4-5 for routing (latency matters).
      Cost: ~$0.001 per classification call.
- [ ] EVALS.md: Note that router accuracy will be measured in Phase 6
      (guardrails phase) as part of the broader red-team / accuracy
      eval — don't build a separate router eval suite here.
- [ ] ARCH.md §5: Update the data flow to reflect the actual
      implementation; PENDING steps from §5 now have real code.
- [ ] RUNBOOK.md §7 (demo flow): step 3 (`/bot why do I keep dying`)
      now has a real answer path; step 4 (Langfuse trace tree) shows
      a real trace.
- [ ] Checklist.md Phase 3.1 ticked.
- [ ] CLAUDE.md §2 status updated.

---

### Phase 3.2 · Bounded LangGraph agent + tools — `feat/13-agent`

**Goal:** The agent path from 3.1 produces real tool-grounded answers.
A LangGraph bounded loop with three tools: `query_wiki` (RAG),
`analyze_loadout` (reads state, returns class + progression stage),
`suggest_next_boss` (reads state + progression, returns recommendation).
Iteration cap graduates P-008.

**The biggest LLM phase in the project.** Each agent turn may make
3-8 LLM calls (router + agent reasoning + N tool calls + final
synthesis). Watch the cost per turn carefully.

#### Closeout
- [ ] LangGraph setup: `app/agent/graph.py`. Bounded loop with
      `StateGraph`. Nodes: `plan_step`, `execute_tool`,
      `synthesize_answer`. Edges enforce loop cap (P-008 — pick a
      number; my guess is 5-8 iterations).
- [ ] Agent prompt: `app/prompts/agent_system.md`. Instructs the LLM
      to call tools to gather information before answering, to cite
      retrieved chunks in its final answer, to refuse if it can't
      ground a claim.
- [ ] Tool: `query_wiki(query: str, game_version: str, k: int = 5)` —
      wraps `RetrievalPipeline.retrieve()`. Returns chunks as a JSON
      list the LLM can read.
- [ ] Tool: `analyze_loadout(state: StatePayload)` — reads equipped
      gear, returns the canonical class (Melee/Ranger/Mage/Summoner)
      using deterministic rules. Pure Python, no LLM call. Cold-start
      fallback (no gear equipped) defers to Phase 3.3's LLM zero-shot.
- [ ] Tool: `suggest_next_boss(state: StatePayload)` — reads
      `downed_bosses` and `hardmode` flags from state, returns the
      next progression target as a string. Pure Python decision tree.
- [ ] Iteration cap enforcement: agent gracefully degrades if it hits
      the cap without converging. Returns a "best-effort" answer from
      whatever chunks it gathered, plus a warning. Graduates P-008
      to D-NNN with the chosen number.
- [ ] Langfuse spans: every tool call is its own span under the agent
      span. The full trace tree for a hard question now shows
      `router.classify → agent.plan → agent.tool_call (query_wiki) →
      rag.retrieve → agent.plan → agent.tool_call (analyze_loadout) →
      agent.synthesize`. This is the "agent debugging is miserable
      without traces" claim made real.
- [ ] Unit tests: `tests/agent/test_graph.py` — mocked LLM responses
      drive the graph through pre-baked tool-call sequences. Cover:
      single-tool path, multi-tool path, loop-cap-reached path.
      `tests/agent/test_tools.py` covers the three tools in isolation
      with fixture state payloads.
- [ ] Integration test (manual, not in CI): send the canonical hard
      question `"why do I keep dying to Skeletron?"` with a state
      payload showing the player has pre-Hardmode gear, no Skeletron
      defeated, low HP. The agent should retrieve Skeletron strategy
      chunks, analyze the loadout's class, and synthesize a
      progression-aware answer. Watch the Langfuse trace.
- [ ] Cost measurement: send 10 hard queries through the agent, record
      median tokens per turn and median cost. Document in EVALS.md as
      operational baseline (not a hard gate).
- [ ] DECISIONS.md: D-NNN graduating P-008 (loop cap) with the chosen
      iteration count and the cost-per-turn measurement. Possibly a
      D-NNN documenting the three-tool choice with rationale (why
      these three, why not more).
- [ ] ARCH.md §5: update the agent step with the real tool list and
      loop bounds.
- [ ] Checklist 3.2 ticked + CLAUDE.md §2.

---

### Phase 3.3 · State payload + LLM zero-shot class fallback — `feat/14-state-class`

**Goal:** The state-payload schema is finalized, `analyze_loadout`
correctly infers class from real gear data, and the cold-start
fallback (LLM zero-shot from an onboarding questionnaire) is wired
in. Resolves D-009.

**Smaller phase than 3.2.** Mostly schema work + tightening
`analyze_loadout` against more realistic state fixtures.

#### Closeout
- [ ] State payload schema finalization: `app/domain/state.py`.
      `StatePayload` Pydantic model with fields:
        - `game_version: str`
        - `class StateGear`: `armor: list[ItemRef]`, `accessories:
          list[ItemRef]`, `held_item: ItemRef | None`
        - `inventory: list[ItemRef]` (top 20 or so by stack/value)
        - `stats: PlayerStats` (HP, MP, defense)
        - `world: WorldState` (`hardmode: bool`, `downed_bosses:
          dict[str, bool]`, `biome: str`)
      The schema must match what the tModLoader client will produce
      in Phase 4.2 — talk to that phase's plan before locking the
      schema.
- [ ] `ItemRef`: `{item_id: int, name: str, prefix: str | None,
      stack: int}`. `item_id` is the Terraria internal ID (matches
      Cargo `Items.itemid`).
- [ ] `analyze_loadout` rule set: deterministic class inference
      from equipped gear. Examples:
        - Full Spectre armor + magic weapon → Mage
        - Hallowed Ranger Helmet + ranger accessories + Megashark →
          Ranger
        - No armor + Copper Shortsword (new character) → defer to
          LLM zero-shot
      The rules are encoded in Python, not in a prompt. The Cargo
      `Items.listcat` ("Ranged weapons", "Magic weapons",
      "Summoning") helps but isn't authoritative on its own.
- [ ] Cold-start LLM zero-shot: when `analyze_loadout` returns
      "unknown" (e.g., new character with no real gear), the agent
      calls the LLM with the state payload + an onboarding prompt
      ("based on this player's inventory and recent actions, what
      class are they leaning toward?"). Returns one of the four
      classes. This satisfies D-009's stated fallback path.
- [ ] Test fixtures: `tests/agent/fixtures/states/` with realistic
      JSON state payloads for each class at multiple progression
      stages (pre-boss Ranger, post-Skeletron Mage, etc.).
      `test_class_detection.py` covers each fixture and asserts the
      expected class.
- [ ] Tests for the LLM fallback path: mocked LLM responses cover
      ambiguous loadouts (mixed gear) and confirm the fallback
      reports a class plus a confidence indication.
- [ ] DECISIONS.md: graduate D-009 from "deferred to future" status
      to "implemented as described." The class detection F1 *is not*
      measured here — there's no labelled dataset and the brief
      explicitly said this was non-grading. Document this in EVALS.md
      §3 (the existing "class detection sanity check, not a gate"
      note) with the actual fixture results.
- [ ] ARCH.md §5: state payload section now has real schema; remove
      "PENDING" marks.
- [ ] Checklist 3.3 ticked + CLAUDE.md §2 → "Section 3 complete;
      Section 4 (auth & game client) next."

---

## Section 4 — Auth & Game Client (Days 7–9)
> _Outline — expand when reached. Auth precedes client work (the client needs `/client/token`)._

### Phase 4.1 · Auth & token exchange — `feat/14-auth`
- Goal: fastapi-users + JWT (signing key from Vault); register/login/guest; `/client/token`; JWT sets RLS context; player/operator roles (ARCH §6).
- **Resolve P-005** (game-client identity) here. Touches: `app/api/auth.py`, `app/infra/auth.py`, `DECISIONS`, `SECURITY.md`. Done-when: end-to-end login + a guest tenant + RLS context proven from a real JWT.

### Phase 4.2 · Mod core: `/bot` + state read — `feat/15-client-core`
- Goal: `ModCommand` `/bot`; read `Main.LocalPlayer` gear/inventory + world flags; build state payload JSON.
- Touches: `client/`. Done-when: `/bot test` logs a correct state payload in-game.

### Phase 4.3 · Token exchange + transport — `feat/16-client-transport`
- Goal: identity → `/client/token` → JWT; async `HttpClient`; render reply via `Main.NewText`.
- Touches: `client/`. Done-when: authenticated call from the mod returns and renders.

### Phase 4.4 · End-to-end — `feat/17-client-e2e`
- Goal: in-game `/bot <question>` → router → agent/RAG → contextual reply, singleplayer.
- Touches: `client/`, `RUNBOOK.md`. Done-when: a real progression question answered correctly in-game.

---

## Section 5 — Web Surfaces (Days 9–11)
> _Outline — expand when reached. Keep the portal minimal (D-011)._

### Phase 5.1 · React config portal — `feat/18-frontend-user`
- Goal: login/register/guest, version dropdown + check, preferences, right-to-erasure button. No chat.
- Touches: `frontend-user/`, `ARCH.md §13.2`. Done-when: a player can register, pick a version, set prefs, request erasure.

### Phase 5.2 · Streamlit admin — `feat/19-frontend-admin`
- Goal: operator login, corpus/version mgmt + re-rag trigger, tenant view, test chat over `/bot/ask`.
- Touches: `frontend-admin/`, `ARCH.md §13.1`. Done-when: full agent path demoable without launching Terraria.

---

## Section 6 — Security, Guardrails & CI (Days 11–12)
> _Outline — expand when reached._

### Phase 6.1 · Guardrails + red-team — `feat/20-guardrails`
- Goal: input/output filter (deterministic + LLM-judge) vs injection / "give me dev items" / toxicity; red-team set (graduate P-006).
- Touches: `app/guardrails/`, `data/eval/`, `SECURITY.md`. Done-when: red-team set passes (0 successful injections).

### Phase 6.2 · Right-to-erasure end-to-end — `feat/21-erasure`
- Goal: `DELETE /me` purges Postgres rows + Redis session; audit-logged.
- Touches: `app/api`, `app/services`, `SECURITY.md`. Done-when: erasure verified empty + audit row written.

### Phase 6.3 · CI eval gates green — `feat/22-ci-eval-gates`
- Goal: `eval-redteam.yml` (PR-triggered, no DB) red on injection success; `eval-rag.yml` thresholds enforced; both green on `main`.
- Touches: `.github/workflows/`, `EVALS.md`. Done-when: a regression turns CI red on purpose, then green when fixed.

---

## Section 7 — Polish & Present (Days 13–14)
> _Outline — expand when reached._

### Phase 7.1 · Isolation demo — `feat/23-isolation-demo`
- Goal: a second tenant to *prove* RLS isolation live (not just assert it).
- Done-when: Tenant A query can't surface Tenant B data, shown end-to-end.

### Phase 7.2 · Deliverables finalize + README — `feat/24-runbook-deliverables`
- Goal: `RUNBOOK.md §demo` numbered click-through; finalize `EVALS/SECURITY/LICENSES`; real `README.md`.
- Done-when: a cold reader can boot and run the demo from the docs alone.

### Phase 7.3 · Demo prep + buffer — `feat/25-demo-prep`
- Goal: rehearse the demo; record; absorb slippage.
- Done-when: clean run-through within time; buffer consumed by overflow from earlier phases.

---

## PR template note

The committed `.github/pull_request_template.md` should list **terra-mind's** deliverables (ARCH / DECISIONS / RUNBOOK / EVALS / SECURITY / LICENSES) and the phase/branch/CI/no-secrets checklist — adapt the field names to this project, don't carry over labels that don't apply here.