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

## Section 3 — Router, Agent & Class Detection (Days 5–7) ✅ COMPLETE

_Phases 3.1 (router + `/bot/ask`), 3.2 (bounded LangGraph agent), and 3.3
(finalized state schema + Cargo-aware class detection + LLM zero-shot fallback)
all shipped. Next: Section 4, Phase 4.1a (backend auth + JWT + token exchange)._

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
- [x] Endpoint scaffolding: `app/api/bot.py` with `POST /bot/ask`.
      Request body schema: `{message: str, state: StatePayload | None}`.
      `StatePayload` is a Pydantic model from `app/domain/` matching
      ARCH.md §5 step 1 (gear, inventory, hardmode, downed bosses,
      biome, game_version). For Phase 3.1 it can be optional/stub —
      the router doesn't use it yet.
- [x] Router prompt: `app/prompts/router.md`. System prompt + few-shot
      examples that classify the user's question into `"faq"` (single
      lookup; "Megashark damage" "Wooden Sword recipe") or `"agent"`
      (multi-step, state-dependent; "why do I keep dying to Skeletron",
      "what should I do next"). Versioned prompt file, loaded at runtime.
- [x] Router service: `app/services/router.py`. Single LLM call to
      `claude-haiku-4-5` (D-003) with the router prompt + user question.
      Parses the classification result. **No state payload in the
      router prompt** — the router just decides the path, doesn't
      consume state. Returns a `RoutingDecision` enum.
- [x] FAQ path: when router returns "faq", call the
      `RetrievalPipeline.retrieve()` from Phase 2.4 with the user
      question + `game_version` from state (default to `"1.4.4.9"`
      if state is absent), top-1 chunk. **Single LLM call to
      synthesize an answer from the chunk** — this is where the user
      actually gets a response. Prompt template:
      `app/prompts/faq_answer.md`. Model: claude-haiku-4-5. Returns
      `{answer: str, source_chunks: list[ChunkRef]}`.
- [x] Agent path stub: when router returns "agent", return a player-facing
      stub message (`app/services/agent_stub.py::_STUB_MESSAGE`). The path
      is exercised by tests; Phase 3.2 fills in the real LangGraph agent.
- [x] Anthropic SDK integration: `app/infra/anthropic.py`. Async client
      loaded at lifespan startup, key from Vault. Wraps the SDK with
      Langfuse generation tracing — every LLM call emits a
      `obs.generation()` event with `model`, `input`, `output`,
      `usage_details` so the cost trail is visible.
- [x] Langfuse trace tree (the graded "traces are real" check): one
      trace per `/bot/ask` request. Verified in live smoke test:
      `http_request → bot.ask → router.classify → router.llm` and
      `faq.answer → rag.retrieve + faq.llm`. Both traces confirmed
      in Langfuse UI.
- [x] Unit tests: `tests/services/test_router.py` (7 tests),
      `tests/services/test_faq.py` (4 tests),
      `tests/api/test_bot_ask.py` (4 tests),
      `tests/infra/test_anthropic.py` (4 tests). 142/142 total pass.
- [x] Integration test (manual, not in CI): smoke test passed 2026-06-11.
      FAQ question returned grounded Megashark damage answer with correct
      source_chunks; agent question returned stub response. ~$0.001 total.
- [x] DECISIONS.md: D-023 — claude-haiku-4-5 locked for router + FAQ.
      Measured costs from live smoke test. Sonnet-4-6 reserved for 3.2.
- [x] EVALS.md: Router accuracy deferred to Phase 6 (guardrails phase)
      as part of the red-team / accuracy eval — no separate router eval
      suite in Phase 3.1. (Noted in EVALS.md §2.)
- [x] ARCH.md §5: Updated — steps 5, 7, 10–11 marked implemented;
      steps 1–4, 6, 8–9 annotated with their pending phase.
- [x] RUNBOOK.md §7.2: Smoke test procedure with two curl commands
      (FAQ + agent paths) and Anthropic refuse-to-boot troubleshooting.
- [x] Checklist.md Phase 3.1 ticked.
- [x] CLAUDE.md §2 status updated.

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
- [x] LangGraph setup: `app/agent/graph.py`. Bounded loop with
      `StateGraph`. Nodes shipped as `plan`, `execute_tools`,
      `synthesize_cap` (renamed from the planned
      `plan_step`/`execute_tool`/`synthesize_answer`). Edges enforce
      the loop cap. **MAX_ITERATIONS = 5** (D-024, graduates P-008).
- [x] Agent prompt: `app/prompts/agent_system.md` (commit 2). Instructs
      the LLM to call tools before answering, cite retrieved facts by
      name, and refuse honestly when it can't ground a claim.
- [x] Tool: `query_wiki(query, *, game_version, k=5, retrieval, ...)` —
      wraps `RetrievalPipeline.retrieve()`. Returns a list of dicts
      (`page_title`/`section`/`content`/`source_url`/`score`) the LLM
      can read; the graph stores `ChunkRef`s (no content) in
      `chunks_seen` for `BotAnswer.source_chunks`.
- [x] Tool: `analyze_loadout(state)` — reads equipped gear, returns
      `class` + `confidence` + `progression_stage` + `needs_llm_fallback`
      via a hardcoded item→class dict (Phase 3.2). Pure Python, no LLM
      call. Cold-start (empty/unknown gear) → `needs_llm_fallback=True`,
      deferred to Phase 3.3's LLM zero-shot (D-009). Phase 3.3 makes
      this Cargo-aware.
- [x] Tool: `suggest_next_boss(state)` — reads `downed_bosses` and
      `hardmode`, returns `next_boss` + `rationale`. Pure Python
      decision tree (pre-HM EoC→EoW/BoC→Skeletron→WoF; post-HM
      mech→Plantera→Golem→Cultist→Moon Lord).
- [x] Iteration cap enforcement: at MAX_ITERATIONS the graph routes to
      `synthesize_cap`, which forces a final answer from gathered
      results. The service layer (`app/services/agent.py`) also wraps
      `graph.ainvoke` in try/except → safe fallback `BotAnswer`, so the
      endpoint never 500s. Graduates P-008 → **D-024** (cap = 5; caveat:
      cap bounds plan→execute cycles, not tool dispatches).
- [x] Langfuse spans: agent calls are traced under an `agent.run` span.
      **Deviation:** the trace tree is *flatter* than the planned
      `agent.plan → agent.tool_call → …` hierarchy — each
      `chat_with_tools` generation event and each `rag.retrieve` span
      are flat siblings under `agent.run` (no per-iteration spans).
      Functional and visible; tighter nesting deferred to **P-013**.
      Token counts render as 0/0 in the Langfuse 2.60.10 UI (**P-009**,
      SDK sends correct data).
- [x] Unit tests: `tests/agent/test_graph.py` (4 tests: immediate
      end_turn, single-tool→end_turn, multi-tool, cap-hit — all with
      pre-baked mocked LLM responses). `tests/agent/test_tools.py`
      (3 query_wiki, 8 analyze_loadout, 9 suggest_next_boss fixtures).
- [x] Integration test (manual, operator smoke test): canonical
      `"why do I keep dying to Skeletron?"` with a Ranger early-pre-HM
      state payload → classified ranger / early-pre-hardmode, retrieved
      5 Skeletron chunks, multi-iteration loop produced a class-aware
      progression-aware answer. Canonical curl now in RUNBOOK §7.3.
- [x] Cost measurement: `scripts/measure_agent_cost.py` + 10-question
      run (12 Jun 2026). Median ~$0.005/call, p95 ~$0.020 (Q05),
      median latency ~7 s. Documented in **D-025** (operational
      baseline, not a hard gate); reproduction steps in RUNBOOK §7.4.
- [x] DECISIONS.md: **D-024** graduates P-008 (loop cap = 5 + three-tool
      roster finalization). **D-025** documents the cost/latency
      profile. Cost methodology + Langfuse caveat noted (P-009).
- [x] ARCH.md §5 step 6: updated with MAX_ITERATIONS=5, the three tools
      by name, and references to D-024 / D-009.
- [x] Checklist 3.2 ticked + CLAUDE.md §2.

**Phase 3.2 follow-up / open polish items (none blocking):**
- [ ] **P-009** — Langfuse 2.60.10 UI shows token usage as 0/0; upgrade
      Langfuse in an observability-polish phase.
- [ ] **P-010** — cache the compiled agent graph on `app.state` at
      lifespan instead of building it per request (~50 ms/call).
- [ ] **P-012** — cap total `chunks_seen` length to bound agent context
      cost (input tokens grow linear-to-quadratic with iterations).
- [ ] **P-013** — open nested per-iteration spans inside the agent graph
      nodes for a tighter Langfuse trace hierarchy.

---

### Phase 3.3 · State payload + LLM zero-shot class fallback — `feat/14-state-class`

**Goal:** The state-payload schema is finalized, `analyze_loadout`
correctly infers class from real gear data, and the cold-start
fallback (LLM zero-shot from an onboarding questionnaire) is wired
in. Resolves D-009.

**Smaller phase than 3.2.** Mostly schema work + tightening
`analyze_loadout` against more realistic state fixtures.

#### Closeout
_Shipped field names differ from this phase's original draft — reconciled to
reality: gear weapon slot is `weapon` (not `held_item`); `downed_bosses` is
`list[str]` (not `dict[str,bool]`); models stay in `app/domain/bot.py` (no new
`state.py`); class signal is Cargo `damagetype` (not `listcat`, finding A1)._
- [x] State payload schema finalization in `app/domain/bot.py` (commit 2).
      `StatePayload`: `game_version: str`, `gear: GearState`
      (`armor`/`accessories`/`weapon: ItemRef | None`),
      `inventory: list[ItemRef]`, `stats: PlayerStats`
      (`life`/`max_life`/`mana`/`max_mana`/`defense`),
      `world: WorldState` (`hardmode: bool`, `downed_bosses: list[str]`,
      `biome: str`). All additive with safe defaults; round-trip +
      backward-compat tests in `tests/domain/test_state_payload.py`.
- [x] `ItemRef`: `{item_id: int=0, name: str="", prefix: str | None=None,
      stack: int=1}`. `item_id` = Terraria `item.type` = Cargo `itemid`
      (canonical, localization-stable); `name` for readability.
- [x] `analyze_loadout` rewritten as a hybrid Cargo-aware classifier
      (`app/agent/class_detection.py`, commits 1+3, **D-026**):
      Cargo `damagetype` gated on `type=weapon` (446 weapons, A2) +
      curated armor/fallback map (Cargo has 0 armor signal, A3) +
      deterministic vote. Pure Python, no LLM in `analyze_loadout`
      itself. `item_id`-primary resolution, `name` fallback.
- [x] Cold-start LLM zero-shot (commit 4): when deterministic detection
      returns `needs_llm_fallback=True`, `execute_tools` (not
      `analyze_loadout`) fires `llm_classify` — one `claude-haiku-4-5`
      call (`max_tokens=8`, prompt `class_fallback.md`) returning one of
      the four classes or `unknown`. Satisfies D-009's fallback path.
- [x] Tests: 8 `analyze_loadout` fixtures (`tests/agent/test_tools.py`,
      unchanged across the swap) against the curated `DEFAULT_CLASSIFIER`;
      `tests/agent/test_class_detection.py` covers the `ItemClassifier`
      tiers (synthetic Cargo fixture), `item_id` precedence, refuse-to-boot,
      and `llm_classify` (mocked Anthropic). No `fixtures/states/` dir —
      payloads built inline.
- [x] Tests for the LLM fallback path: `llm_classify` recognized/unknown/
      noisy/off-vocab replies + a graph-level test proving the fallback
      fires on empty gear and merges its guess into the tool_result.
- [x] DECISIONS.md: **D-026** graduates D-009 to fully implemented (hybrid
      design + the 446-weapon / 0-armor / ~$0.0002-fallback numbers + the
      CI/gitignore constraint). No F1 gate (no labelled dataset, non-grading);
      EVALS.md §3 updated with the actual fixture coverage.
- [x] ARCH.md §5 step 1 + §13.3: finalized `StatePayload` schema and the
      `item_id`-canonical note; class-detection refs point to D-026.
- [x] Checklist 3.3 ticked + CLAUDE.md §2 → Section 3 complete; Phase 4.1a
      (backend auth) next.

---

## Section 4 — Auth & Game Client (Days 7–9)

**Sequencing principle:** the entire auth + tenant-isolation security story lands and is **proven in Python/CI (4.1a + 4.1b) before any C# is written.** The mod phases (4.2–4.4) consume an already-proven backend. Decisions resolved for this section: **D-027** (mod login-once / token-persist, resolves P-005), **D-028** (config-driven backend URL, resolves P-011), **D-029** (Redis-denylist session revocation).

### Phase 4.1a · Backend auth & token exchange — `feat/15-auth`

**Goal:** `fastapi-users` + JWT (signing key from Vault, scaffolded in 1.5); register / login / guest; the saved-token→access-JWT exchange (**shipped as `POST /auth/refresh`** — `/client/token` was folded in, see closeout); JWT sets the RLS tenant context in the service layer; player/operator roles; the Redis denylist for logout/revocation (D-029). **Fully CI-testable; must land 100% green before any C#.**

#### Closeout
_Shipped vs the draft: token issuance is **custom** (`app/infra/jwt_tokens.py`,
pyjwt) — fastapi-users supplies the user model + argon2id hashing + register;
`/client/token` was **dropped** and folded into `POST /auth/refresh` (D-027/D-029)._
- [x] `app/infra/auth.py`: fastapi-users wiring bound to the existing `Tenant`
      table (no migration); **argon2id** hashing; user manager + register router.
      `app/infra/jwt_tokens.py`: custom access(30m)+refresh(30d) JWTs (HS256, Vault
      key from `app.state`, claims `sub`/`role`/`jti`/`type`/`exp`).
- [x] `app/api/auth.py`: `POST /auth/register` (privilege-safe — strips
      is_superuser), `/auth/jwt/login` → `{access, refresh}`, `/auth/refresh`
      (refresh→access; the mod's saved-token exchange), `/auth/logout`
      (denylists the refresh `jti` + `session.revoked` audit), `/auth/guest`
      (access-only ephemeral tenant).
- [x] RLS context setter in **services/** (`app/services/rls.py`,
      `set_config(..., true)` = SET LOCAL); **D-030** fail-closed NULLIF policy
      (migration `c2d3e4f5a6b7`). Built + proven; invoked at the first
      tenant-scoped op (not `/bot/ask`, which has none — approved commit-3
      deviation). `terramind_app` non-superuser in tests.
- [x] Session revocation (D-029): `app/memory/denylist.py` Redis denylist keyed
      `denylist:jti:{jti}`, TTL = remaining lifetime; `/auth/refresh` + the
      access-token gate check it; `session.revoked` audit row on logout.
- [x] Roles: `require_access_token` (player) + `require_operator` (operator-403)
      dependencies (`app/api/deps.py`). `/bot/ask` gated by the access JWT.
- [x] Tests (CI, real Postgres via testcontainers + fakeredis, no mod):
      register / login / refresh / logout / guest; access-token claims + 30-min
      TTL; **refresh token rejected at `/bot/ask`** + at resource gate; denylisted
      token → 401; operator-403 both directions; RLS proof (uncontexted → 0 rows,
      cross-tenant invisible, WITH-CHECK block). `tests/api/test_auth.py`,
      `tests/api/test_roles.py`, `tests/api/test_bot_ask.py`,
      `tests/services/test_rls_context.py`. 236/236 green.
- [x] Deliverables: D-006 TTL graduation; D-029 revised (token model, no
      rotation/P-014); **D-030** (NULLIF fail-closed); ARCH §6/§7 (auth flow +
      `/client/token`→`/auth/refresh`); SECURITY §3/§4/§6; P-014 registered.
- [x] Local gate green (Docker up for testcontainers). **Done-when met:** register
      + login + guest + a real JWT proving the RLS context mechanism — all in CI.
      **Checklist 4.1a ticked + CLAUDE §2.** Next: Phase 4.1b on
      `feat/16-rls-isolation`. _(Standing flag: the first Docker-dependent CI run
      must go green before the 4.1a PR merges.)_

### Phase 4.1b · RLS isolation proof + audit — `feat/16-rls-isolation`

**Goal:** prove **"tenant isolation is the security story" (CLAUDE §4.3) in Python, before the mod exists.** Two-tenant isolation demonstrated end-to-end through the real API + RLS; erasure scoped to one tenant; audit rows for auth/erasure events. This is the phase that locks the headline control in CI; Phase 7.1 later *re-demos* it live.

#### Closeout
_Shipped: memory wired into `/bot/ask` (the per-tenant data isolation operates
on) via the two-short-transactions RLS pattern; the proof drives the real path,
not direct inserts. Path: `tests/services/test_rls_isolation.py` (not the
earlier `tests/test_rls_isolation.py` reference — reconciled here + SECURITY §3)._
- [x] Short-term memory wired (D-031, P-004): `app/memory/short_term.py` (N=20 /
      TTL=2 h, injected Redis, redaction-on-write) + `app/services/memory.py`
      dual-write (Postgres `messages`/`sessions` under RLS + Redis) into
      `/bot/ask` via **two short transactions** (resolve_session → agent, no DB
      held → record_turn), each re-setting `set_tenant_context` (D-030). Read
      path (`get_history`) built, not yet consumed (documented).
- [x] `tests/services/test_rls_isolation.py`: two real tenants through the **real
      `/bot/ask` path** as non-superuser `terramind_app`; under B's context a raw
      SELECT of `messages` returns **zero** of A's rows (by tenant, count,
      content). No application `WHERE` — Postgres enforces. Falsifiable (fails if
      RLS off).
- [x] `DELETE /me` data erasure (D-032): purges the tenant's messages/sessions
      (RLS-scoped DELETE) + Redis keys + `tenant.erased` audit (with
      `deleted_rows`). Proven physical (not masked) via the **owner connection**
      in `tests/api/test_erasure.py`; B's rows survive. Guests purged too. Keeps
      the account row (full account deletion → P-015).
- [x] Audit rows: `auth.login` (login + guest, not refresh), `session.revoked`
      (logout), `tenant.erased` (erasure) — written; operator read endpoint is
      Phase 5.2.
- [x] Denylist check wired into the authed request path (`require_access_token`,
      4.1a) — a revoked token cannot reach `/bot/ask` or `DELETE /me`.
- [x] EVALS.md §4b: isolation + erasure registered as **blocking security
      tests**. SECURITY.md §3 = isolation PROVEN end-to-end (+ erasure scope/PII).
      DECISIONS D-031/D-032, P-015; ARCH §5/§7/§8 implemented.
- [x] Local gate green (Docker up); **248/248**. **Checklist 4.1b ticked +
      CLAUDE §2.** Security story locked in CI before any C#. _(Standing flag:
      the Docker-dependent CI run must go green before the 4.1b PR merges.)_

### Phase 4.2 · Mod core: `/bot` command + state read — `feat/17-client-core`

**Goal:** the tModLoader `ModCommand` `/bot`; read `Main.LocalPlayer` gear/inventory + world flags; build the **finalized Phase 3.3 `StatePayload` JSON** (item_id primary, prefix/stack, `PlayerStats`, inventory, world). **Not CI-testable** (ARCH §13.3 "No CI" for the mod) — ticks on **manual** verification.

#### Closeout
_Fresh build in `client/TerraMind/` (spike was throwaway). **Verified in-game,
not CI** (ARCH §13.3) — 7 `/bot test` runs against a live character via
`client.log`. Schema corrections caught pre-build: `game_version` is top-level
(not in world); `name`/`biome` non-nullable._
- [x] `client/TerraMind/`: `BotCommand : ModCommand` (`CommandType.Chat`,
      `Command => "bot"`), invoked in-game as `/bot <message>`. Message captured
      (not sent — 4.3 wires it). Logs full JSON via `Mod.Logger`; chat summary via
      a `QueueMainThreadAction` marshal helper (carried for 4.3, spike finding).
- [x] State read (`State/StateReader.cs`): `armor[0..2]`→`gear.armor`,
      `armor[3..9]`→`gear.accessories`, `HeldItem`→`gear.weapon`,
      `inventory[0..49]`→`inventory`; `item.type`→`item_id`, `Name`→`name`,
      `Lang.prefix`→`prefix` (null if unmodified), `stack`; `statLife`/
      `statLifeMax2`/`statMana`/`statManaMax2`/`statDefense`→`stats`;
      `Main.hardMode`+`NPC.downed*` (`WorldGen.crimson` EoW/BoC split)→`world`;
      `Player.Zone*`→biome. Boss names in `State/BossFlags.cs` normalize to the
      backend's `_normalize` tokens.
- [x] Serializes to the exact `StatePayload` shape (`State/StateDtos.cs`, explicit
      `[JsonPropertyName]` snake_case); `game_version="1.4.4.9"` (D-016). 422-risk
      surface confirmed clean in-game.
- [x] **Manual done-when — MET (verified in-game, 7 runs via `client.log`):**
      JSON tracks live state — `gear.weapon`=`HeldItem` (changed as held item
      switched), armor/accessory split correct (Wood armor → `gear.armor`,
      unequip → `inventory`), `defense` tracks armor (0→1→3→0), `life` tracks HP,
      `max_life`/`max_mana` correct (100/20 fresh; `statLifeMax2`/`statManaMax2`
      names verified), prefixes render as **names** ("Lazy"/"Annoying", null when
      unmodified — `Lang.prefix` works), shape matches schema exactly. _(Nullable
      `string?` CS8632: the `<Nullable>enable</Nullable>` csproj property does NOT
      reach the tModLoader compile — corrected in Phase 4.3 with per-file
      `#nullable enable` directives; see `client/VERIFICATION.md`.)_
- [x] **Verified-by-adjacency (not directly exercised, low risk):**
      `downed_bosses` (no bosses down on the test character — but `BossFlags.cs`
      **compiled clean**, so all `NPC.downed*`/`WorldGen.crimson` names are valid)
      and `accessories` (none equipped — same `armor[]` slot read as the working
      armor path). Noted for honest coverage.
- [x] RUNBOOK §10: build (copy→ModSources→Build+Reload), run `/bot test`, where
      `client.log` is, sample correct payload, scrutiny list. **No CI gate — the
      PR's gate is this documented in-game verification.**

### Phase 4.3 · Mod login + token persistence + transport — `feat/18-client-transport`

**Goal:** chat-command login (D-027, 4.3 revision): `/bot login <user> <pass>` → `/auth/jwt/login` (form-encoded) → discard password → persist token pair to `token.json` (config holds the backend URL **only**, not creds); each launch exchange the refresh token at `POST /auth/refresh` → fresh access JWT (also on a 401); `/bot logout` deletes `token.json` + `POST /auth/logout` (denylist); single static async `HttpClient` (spike §findings); render reply via `Print()`/`QueueMainThreadAction`. **Not CI-testable** — manual done-when, evidence in `client/VERIFICATION.md`. Resolves P-005's client half.

#### Closeout
- [x] **Chat-command login** (4.3 revision of D-027): `/bot login <user> <pass>` →
      `POST /auth/jwt/login` (**form-encoded** — the OAuth2PasswordRequestForm trap),
      **password discarded** after the one call (in-memory only, never on disk/logged).
      Config holds the **backend URL only** (D-028), not creds — `ClientSide ModConfig`
      auto-persists, so config creds would be a plaintext password on disk. _(commit 1)_
- [x] **Token persistence + restore:** token pair saved to `token.json` under
      `Main.SavePath/TerraMind/` (**tokens only, no password** — `cat`-confirmed); loaded
      on launch, fail-soft on missing/corrupt → fall back to login. World-entry
      confirmation closes the silent-restore gap. _(commit 2; `client/VERIFICATION.md`)_
- [x] **`/auth/refresh` on launch + on 401:** a restored session refreshes its access
      token at world entry (`Web Request: /auth/refresh` log-confirmed — not a cached
      token) and a mid-session 401 triggers the same refresh + one retry (shared
      `AuthFlow`) → durable past the 30-min access TTL. _(commit 3)_
- [x] **`/bot logout`:** deletes `token.json` locally **and** `POST /auth/logout`
      (denylists the refresh `jti` server-side, D-029) → re-login required next launch,
      old token rejected. _(commit 3)_
- [x] **Transport:** a single static `HttpClient` (spike §); state read on the GAME
      thread pre-`await`, fire-and-forget with a `thinking…` first, **every `Main.*` via
      `Print()`/`QueueMainThreadAction`** (spike §critical); real `AskResponse`
      (`answer`+`session_id`) parsed, `session_id` threaded for memory continuity.
- [x] **Manual done-when (verified in-game, no CI):** authed `/bot` renders in-game;
      the login **survives a full Terraria restart** (persist + refresh proven); `/bot logout`
      forces re-login (`token.json` gone via `ls` + server denylist). All evidenced
      **verbatim** from `client.log` in `client/VERIFICATION.md` — **the PR's gate**.
- [x] **RUNBOOK §10 + SECURITY §4:** login/logout flow + token-only / password-never-stored
      documented. Build clean: **0 errors / 0 warnings** after fixing the 4.2 nullable claim
      (csproj `<Nullable>` never reached the tML compile → per-file `#nullable enable`;
      Checklist 4.2 + csproj comment corrected). **P-016** logged (agent under-uses live state).

### Phase 4.4 · End-to-end in-game — `feat/19-client-e2e`

**Goal:** in-game `/bot <question>` → router → agent/RAG → contextual, progression-aware reply, singleplayer, full real flow. **Not CI-testable** — manual done-when. This is the Section-4 payoff: the production chat surface working end to end.

#### Closeout
- [x] Full path live: `/bot <question>` from inside Terraria → JWT-authed
      `/bot/ask` → router → agent (Cargo class detection + RAG) → reply rendered
      via `Print()`. Verbatim in `client/VERIFICATION.md` §4.4 (`routing=agent`,
      session threaded). **Both router paths fire** — `faq` for "what does the
      Confused debuff do?", `agent` for "skeletron" / "what next" (4.3 hit only agent).
- [x] State-dependent correctness: same "what should I do next?" under **melee**
      vs **ranger** loadouts → different class-appropriate advice (Sword/Spear vs
      bow/arrows/ammunition), class read from real equipped gear (D-026). The live
      state drives the answer.
- [x] **P-016 fixed (the one contained prompt fix):** intermittent grounding →
      reliable — one grounding instruction in `agent_system.md` (live state is
      available every turn via the tools; ground first, never ask for lookupable
      state). After-pass: 3/3 grounded under one loadout, none asked for context;
      broad measurement deferred to Section 6's eval harness. `client/VERIFICATION.md` §4.4.
- [x] **Manual done-when (verified in-game, no CI):** a real progression question
      answered correctly + progression-aware end to end with live state; both FAQ
      and agent paths exercised; the in-game turn produces **one clean Langfuse
      trace** (`bot.ask → router → agent/faq → rag.retrieve + llm`, real token
      counts). All in `client/VERIFICATION.md` §4.4 — **the PR's gate**.
- [x] RUNBOOK §10: the in-game demo click-through (stack up → config → `/bot login`
      → FAQ Q → hard Q → swap gear → different answer → Langfuse trace) added.

---

## Section 5 — Web Surfaces (Days 9–11)

Goal: the two web surfaces over the proven backend — the React **config** portal (player account management, NOT chat — D-011) and the Streamlit operator/test bench (corpus/version admin + the test chat that's the demo fallback if the live game breaks, RUNBOOK §7.1). Both are mostly FRONTEND WIRING to already-built, CI-green endpoints from Section 4 — the main risks are CORS, browser token handling, and admin endpoints that may not exist yet (audit first).

> **D-011 revised (Section 5):** the React portal is upgraded from "minimal forms, may degrade to Streamlit" to a **polished** demo surface — conscious override, scope cost accepted, logged in DECISIONS. Guardrail: polished means clean/consistent/presentable, NOT a CSS rabbit-hole. Timebox the styling; if it starts eating Section-6 time, stop at "presentable." The grade is in Sections 6-7 (the evals), not the portal's pixels.

### Phase 5.1 · React config portal — `feat/20-frontend-user`
Player-facing CONFIG surface (D-011). No chat. Vite + React. Polished (D-011 revision). Wires endpoints already built + CI-green in Section 4.

- [x] **Endpoint reality check (Part A):** confirmed against the routers — `/auth/register`, `/auth/jwt/login` (form), `/auth/guest`, `DELETE /me` exist; **`/versions` and `/me/preferences` did NOT** → built them (build-now per the audit).
- [x] **CORS (Part A):** the API had no CORS middleware (the mod was C#, no browser). Added a **locked-origin** allow-list — `add_cors`, origin from env (default localhost:5173), **never `*`** (rejected in code + tested).
- [x] `frontend-user/` scaffold: Vite + React + TypeScript, single bundle (`tsc && vite build` green). Deps react/react-dom/vite + dev @vitejs/plugin-react/typescript/@types — justified in LICENSES §6 (dev-only).
- [x] **Auth:** login / register / continue-as-guest; access+refresh pair in `localStorage` (**token-only, no password**); Bearer on authed calls; **401 → `/auth/refresh` + retry**, else re-login (guests access-only).
- [x] **Version:** dropdown from `GET /versions` (public corpus metadata; one version now — `1.4.4.9`).
- [x] **Preferences:** GET on load + PATCH on save (incl. selected version); reflects saved state; **persists across reload** (verified in-browser).
- [x] **Account / erasure:** `DELETE /me` behind a confirm step (destructive, D-032); success state. **Hidden for guests** (no persisted data); preferences **retained** (D-032 extended).
- [x] **Polish (timeboxed):** clean dark layout, labeled forms, loading states, readable errors (parsed `detail`, not raw JSON), basic responsive. Stopped at clean. **`localStorage` = token only**; all else React state. _(Design-token SKILL unavailable → standard defaults.)_
- [x] **Compose:** `frontend-user` builds (node → nginx) on `:5173`, `depends_on api: service_healthy` (api `start_period` bumped 5s→150s for a clean cold `up`).
- [x] **Manual verify (done-when):** verified in-browser — register → version → prefs persist across a HARD reload → erasure (data gone + logged out; re-login shows prefs survived); guest path works.
- [x] CI green: backend **255 tests** (ruff/format/mypy/pytest) incl. CORS + RLS-prefs isolation; portal builds clean (no frontend CI wired). `ARCH.md §13.2`, `LICENSES.md §6`, D-011 revision + P-017 + D-032 extension in `DECISIONS.md`. **5.1 done.**

### Phase 5.2 · Streamlit operator/test bench — `feat/21-frontend-admin`
Operator surface + THE DEMO FALLBACK (RUNBOOK §7.1). Full-parity test chat is the priority (exercises the exact /bot/ask path without Terraria).

- [x] **Admin-endpoint audit (backend-first):** audited the routers — **none** of `/admin/*` existed (+ the operator bootstrap was documented in RUNBOOK §3 but unbuilt). Per-endpoint: **built** `/admin/tenants` + `/admin/audit-log` (+ the bootstrap); **deferred** `/admin/versions/check` (P-018) + `/admin/rerag` (P-019 — the `build_corpus.py` script is the must-have). The no-RLS + `terramind_app` SELECT-grant facts were verified against the migrations.
- [x] **Operator login:** Streamlit → `/auth/jwt/login`; the bench is JWT-role-gated (player blocked) and the backend `require_operator` (403) is the real enforcement. First operator via `app/entrypoints/bootstrap_operator` (RUNBOOK §3 — now honest, command pointed at nonexistent code before).
- [x] **TEST CHAT (the demo fallback):** 3 preset StatePayloads (melee pre-boss / ranger post-EoC / mage post-Plantera — **real Cargo item_ids** → truthful class detection: 3507 melee, 98 ranger, 518 mage) + a question → `POST /bot/ask` → renders answer + **routing** + session_id, with the raw payload shown. Verified each gives class-distinct, progression-aware answers (melee→sword, ranger→bow, mage→Golem); FAQ routes `faq`.
- [x] **Corpus & Versions:** stored versions via `GET /versions` + a note that re-rag is `scripts/build_corpus.py` (P-019 — no button).
- [x] **Tenants / audit:** the two operator views `GET /admin/tenants` + `GET /admin/audit-log` (load in-browser — tenants cross-tenant, audit shows `tenant.erased` + `auth.login`).
- [x] **Compose:** real `frontend-admin` Streamlit service on `:8501` (server-side calls → **no CORS**), `depends_on api`. Cold `down && up --build` comes up clean in **one** command (api `start_period` 150→**240s** + `retries` 12 — fixed a third false-alarm, proven by a cold boot).
- [x] **Manual verify (done-when):** operator login → test chat preset → agent answer + routing render (no game); versions/tenants/audit load; **player blocked**. Verified in-browser; the test chat is the RUNBOOK §7.1 demo-fallback artifact.
- [x] CI green (backend **259 tests**; bench has no CI — Streamlit, like the React portal). `ARCH.md §13.1`, RUNBOOK §7.1 + §3, DECISIONS (P-018/P-019 + D-017 generalized), LICENSES (streamlit/httpx). **5.2 done — Section 5 complete.**

### Phase 5.3 · Operator-triggered re-rag (background job) — `feat/23-rerag-job`
> **Scope addition (reverses P-019 → D-033).** P-019 deferred the re-rag
> *button* ("script is must-have, button is stretch"). This phase reverses
> that — operator-triggered re-rag as a **robust background job** (RQ
> worker on the existing Redis + retries + restart-survival), with a
> single-job 409 guard and streamed progress. **Conscious reversal,
> accepted cost: a worker/broker infra build ahead of the graded Section
> 6.** **Scope locked (D-033):** re-embed the **cached** corpus now
> (`build_corpus.py` path — deterministic, no live-wiki egress in the
> worker); a re-scrape step is a documented **seam**, not built. The job
> uses the **idempotent upsert, NEVER `--force`** (the audit found
> `--force` leaves a half-deleted version on mid-job death; the upsert key
> `(page_id, chunk_index, game_version)` converges safely on retry).
> Built in **4 staged commits**, green at each.

**Plan-first (done):**
- [x] **Reversal logged** — P-019 → **D-033** in DECISIONS (reversal +
      rationale + accepted cost + locked scope). _(commit 1)_
- [x] **Audit `build_corpus.py` + stack** — found: it reads the **cached**
      `pages/`+`cargo/` (does **not** scrape); the upsert
      `ON CONFLICT (page_id, chunk_index, game_version) DO UPDATE` is
      **already retry-idempotent** (no dupes, no half-version) — but
      `--force` (delete-then-insert) is **not** (half-deleted version on
      mid-job death) → the job uses the upsert, never `--force`; progress
      via a thread-through callback; worker needs DB + data volume RW +
      model + Redis, **no Vault**.

**Commit 1 — worker/broker infra:**
- [x] `rq` runtime dep (+ LICENSES, mypy override); `uv lock && uv sync`.
- [x] `worker` compose service — api image, `rq worker rerag`,
      `DATABASE_URL` + data volume **RW** + Redis (`RQ_REDIS_URL`),
      `depends_on` db/redis, **no Vault**, `restart: unless-stopped`.
- [x] `app/jobs/` — sync RQ queue wiring (`queue.py`, name `rerag`) +
      a trivial `smoke.py:ping()` no-op job.
- [x] **Round-trip test** — enqueue `ping` → `SimpleWorker(burst)` on
      fakeredis → asserts `finished` + `"pong"` (`tests/jobs/test_smoke.py`).
- [x] **Cold-boot check** — `down && up --build`: worker comes up, doesn't
      break the clean boot (api still flips healthy, frontends start).
- [x] A-gate green (ruff/format/mypy/pytest incl. the round-trip).

**Commit 2 — `build_corpus` progress refactor (done):**
- [x] Extract a callable `run_build(version, db_url, *, force=False,
      progress=…)`; CLI unchanged (default print cb); progress threaded at
      the report points (`loading` → `embedding` to 100%). Default
      `force=False` = the idempotent upsert (the worker's retry-safe path,
      D-033); `--force` stays CLI-only, never the job. Existing corpus
      tests green + a new test asserts the callback fires and the build
      still upserts. A-gate green (262 tests).

**Commit 3 — API + job + guard (done):**
- [x] `rerag_jobs` table (migration `e4f5a6b7c8d9`) — minimal (id, version,
      status, stage/done/total, created/started/finished, error);
      **operator/cross-tenant → NO RLS policy, `terramind_app` grant +
      `require_operator`-gated** (D-017 two-categories), not a fail-closed
      tenant policy. Confirmed in the migration.
- [x] Job fn (`app/jobs/rerag.py`) — sync worker entrypoint: marks running
      → `run_build(force=False, progress=cb)` writing the Redis hash + the
      durable row → on success `corpus.reragged` audit + succeeded + release
      lock; on failure record error + re-raise (RQ retries, idempotent).
- [x] Single-job guard — `SET rerag:lock NX EX` → **409** if held; worker
      releases on finish + heartbeats the TTL each tick.
- [x] `POST /admin/rerag` (202 + job id; 409 if busy) +
      `GET /admin/rerag/status/{id}` (durable row + live progress overlay),
      operator-gated. Tests: start→id, 2nd→409, status poll/404, player→403
      on both, + the job fn (run_build faked) succeeds/audits/releases.
- [x] **Relocated `run_build` → `app/rag/corpus_build.py`** (the worker
      image ships `app/` not `scripts/`; avoids an app→scripts inversion).
      `scripts/build_corpus.py` is now a thin CLI. **Fixed** the sync DSN to
      `postgresql+psycopg://` (psycopg2 is not a dep — the worker would have
      crashed at engine creation). A-gate green (266 tests).

**Commit 4 — UI + close (done):**
- [x] Streamlit Versions tab: re-rag button + version select + a
      `st.fragment(run_every=2)` polling progress bar (stage + done/total) →
      succeeded/failed terminal; 409 → "already running". Replaces the
      "script, not a button" note.
- [x] **Verified in-stack (the payoff — real worker, real corpus).** Fresh
      operator → `POST /admin/rerag` → **202** + job_id; 2nd → **409**;
      worker embedded **5157/5157** pages (~5.5 min), progress streamed
      `300→5157`, job **succeeded**; a **`corpus.reragged`** audit row
      landed; `rag_chunks` for 1.4.4.9 = **22,173** (queryable). Proves
      commit 3's relocation + psycopg3 fixes on the real worker+DB+model
      path (the unit tests faked `run_build`).
- [x] **Found + fixed live:** RQ's 180s default `job_timeout` killed the
      first run at 2550/5157 → set `job_timeout=1800` on enqueue (+ unit
      assertion). (Also: a build-cache disk-full — environmental, freed.)
      Logged P-020 (lock-released-before-retry, single-worker-harmless) +
      P-021 (worker/api re-download the model on rebuild → share HF cache).
- [x] A-gate green; `ARCH.md` (§2 worker + §7 endpoints + §10 re-rag flow +
      §13.1 button), RUNBOOK §4.1, DECISIONS (D-033 closeout + P-020/P-021),
      Checklist 5.3, CLAUDE §2. **5.3 done — re-rag button shipped (D-033).**

---

## Section 6 — Security, Guardrails & CI (Days 11–12)

Goal: the graded core — guardrails that block misuse, a red-team set that
proves it (0 successful injections), and CI eval gates that turn a
regression RED. This is where Project Rule 4 ("the evals are the grade")
is satisfied, and where P-006 (guardrail/red-team set) + P-016's broad
measurement land. Mostly NEW backend (guardrails) + CI wiring; 6.2 is
verify-not-build (erasure already exists from 4.1b).

### Phase 6.1 · Guardrails + red-team set — `feat/24-guardrails`
> **The graded core (Project Rule 4).** Resolves P-006 → **D-034**:
> **deterministic-first** guardrail (Tier-1 regex, zero-LLM common path) +
> an **escalation LLM-judge** (haiku, ambiguous band only — not every
> turn, D-003) on both `/bot/ask` surfaces; 3 categories (prompt injection
> / game-jailbreak / toxicity); block → generic refusal + `guardrail.blocked`
> audit (D-017). Red-team set keyed on **adversarial diversity** + benign
> controls; gate `redteam.max_successful_injections: 0` (harness compares
> **directly** — the key has no `_min`/`_max` suffix, by design). **5 staged
> commits.**

**Plan-first (done):**
- [x] **P-006 → D-034** in DECISIONS (architecture + accepted-coverage-risk-
      mitigated-by-the-gate reasoning).

**Commit 1 — deterministic core (done):**
- [x] `app/guardrails/`: domain (`Verdict{blocked, category, reason}`,
      `Category` enum, the player-facing refusal constant) + per-category
      Tier-1 rule sets + `check_input_deterministic` /
      `check_output_deterministic` (regex, **zero LLM**).
- [x] Fast unit tests, **no LLM**: each category's obvious cases BLOCK, and
      the **benign-passes** cases PASS (over-block guard from the start —
      "beat the Moon Lord" / "what does Zenith drop" / "get dev items
      legitimately"). Tier-1 tuned for **precision** (recall → Tier 2).
- [x] A-gate green.

**Commit 2 — LLM-judge + escalation (done):**
- [x] `app/guardrails/judge.py` (reuses `AnthropicClient`, haiku, **fail-
      closed** on error/garbage) + `app/prompts/guardrail_judge.md` (loaded
      in lifespan; **refuse-to-boot** if absent) + `check_input`/`check_output`:
      deterministic hard-block / clear-benign short-circuit (no LLM), only
      the **suspicion net** escalates to the judge. The net errs **broad**
      (favor escalating); its coverage is tuned by commit 3's red-team gate.
- [x] Unit tests with a **mocked** judge (no real LLM): hard-block & clear-
      benign skip the judge (`chat` not called), ambiguous escalates once &
      honors the verdict, reply parses / fails closed. A-gate green (**319**).

**Commit 3 — red-team set + harness (done):**
- [x] `data/eval/redteam.jsonl` (47 records: 30 attacks across distinct
      techniques/category + 17 benign controls incl. borderline-legit) +
      `app/eval/redteam/harness.py` + `tests/test_eval_redteam.py`
      (`@pytest.mark.redteam`, deselected from default `pytest`). Harness routes
      input→`check_input`, output→`check_output`; compares `successful <=
      max_successful_injections` **directly** (the key has no `_min`/`_max`
      suffix — `passes_threshold` raises on it, per the audit).
- [x] **Real run (API key, real judge) — honest before/after:** first run
      **13 successful / 0 over-block** (the set genuinely probed the filter;
      every slip was the suspicion net failing to escalate, not the judge).
      Widened the input net (toxicity-/jailbreak-/injection-soft) + output net
      (leak/compliance/toxicity) → 2; strengthened the judge prompt (abuse-at-
      assistant; referencing-its-own-rules) → 1; generalized Tier-1 toxicity
      (intensifier gap + verbless strong-insult) + Tier-1 output meta-leak
      (`stay in character` / `rules I was handed`) → **0 successful / 0
      over-block, stable across 3 runs**. Tunings are general classes, not the
      verbatim set strings. A-gate green (324 + 1 deselected).

**Commit 4 — wire into `/bot/ask` + close 6.1 (done):**
- [x] Input hook (after `resolve_session`, before routing — ARCH §5 step 4) +
      output hook (before `record_turn`/return — step 9), via a thin
      `app/services/guardrails.py` (keeps the LLM-judge call in the service
      layer). Block → generic refusal + `guardrail.blocked` audit
      (operator/cross-tenant, no RLS — D-017); input-block skips routing+answer.
- [x] Integration tests (mocked judge): attack → blocked, **router never
      called**, audited; benign → passes through (routing=faq); leaking output
      → replaced with the refusal + audited. **327 tests** (+3), 1 deselected.
- [x] Closeout: `SECURITY.md §8` (two tiers + gate + the self-validation
      argument), `EVALS.md §2` (set at `data/eval/redteam.jsonl` + the 13→0
      convergence table), `eval-redteam.yml` paths extended (set + judge prompt;
      needs the `ANTHROPIC_API_KEY` secret), Checklist 6.1, CLAUDE §2.
      **6.1 done — the graded core: real red-team gate at 0 successful.**

### Phase 6.2 · Right-to-erasure — VERIFY end-to-end — `feat/25-erasure`
> **Mostly built already** (4.1b: `DELETE /me` purges Postgres + Redis,
> audit-logged, owner-connection physical-deletion test; 5.1/D-032:
> retains preferences). This phase = prove it end-to-end as a live demo +
> close any gap, NOT rebuild it.
- [x] **Audit (verify-not-rebuild):** erasure built (4.1b) + 3-of-4
      guarantees already tested — (a) Postgres rows physically gone
      (owner-connection), (b) Redis cleared, (c) `tenant.erased` audit —
      plus guest erasure. **Gap: (d) D-032 "prefs RETAINED" was asserted
      but UNTESTED.** 6.1 added no new tenant-scoped content to purge
      (`guardrail.blocked` = operator-audit, no PII, retained by design).
- [x] **Closed the gap:** `test_erasure.py::test_delete_me_retains_preferences`
      — `PATCH /me/preferences` → erase → owner-connection `tenant_preferences`
      count `== 1` (retained) + post-erasure `GET /me/preferences` still
      returns it. A-gate green (**328 tests**).
- [x] **Live in-stack capture** (reproducible, like 5.3): player + prefs +
      4 messages / 2 sessions / 2 Redis keys → `DELETE /me` → content **0**,
      Redis cleared, `tenant.erased deleted_rows=6`, **prefs + account row
      retained**, `GET /me/preferences` still returns `1.4.4.9`.
- [ ] Demo path: erasure via the React portal button (5.1) — **operator
      does the in-browser click** (the brief's "delete my data" demo).
- [x] `SECURITY.md §3/§4/§6` reflect the proven flow (content erased;
      account/audit/`guardrail.blocked`/preferences retained). Tick 6.2.

### Phase 6.3 · CI eval gates green — `feat/26-ci-eval-gates`
- [ ] **`eval-redteam.yml`** (PR-triggered, no DB — exercises the
      guardrail filter on inputs/outputs): RED on any successful
      injection, green at 0. Runs on PRs touching `app/guardrails/`, the
      red-team set, or the guardrail prompts.
- [ ] **`eval-rag.yml`** (manual-dispatch, needs the live corpus DB):
      enforces the `eval_thresholds.yaml` hit@k / MRR floors; a
      regression below threshold fails the job.
- [ ] **Prove the gate works**: deliberately introduce a regression
      (a guardrail bypass / a threshold miss) → CI turns RED → fix → green.
      This is the "a regression must turn the build red" requirement,
      demonstrated.
- [ ] **P-016 broad measurement** (deferred from 4.4): measure the
      agent-grounding fix across the RAG golden set / progression
      questions (not just the in-game n≈5) — record whether it
      helps/regresses, as a number. Lands here with the eval harness.
- [ ] CI green on `main`; `EVALS.md` (both gates + the regression proof),
      final numbers table started. Tick 6.3 → Section 6 complete.

---

## Section 7 — Polish & Present (Days 13–14)
> _Outline — expand when reached._

### Phase 7.1 · Isolation **re-demo** (live) — `feat/25-isolation-demo`
- Goal: live re-demonstration of the isolation **already proven in CI at Phase 4.1b** — a second tenant shown end-to-end so the defense sees it, not first proof.
- Done-when: Tenant A query can't surface Tenant B data, shown live end-to-end (the `tests/services/test_rls_isolation.py` gate from 4.1b is the proof; this is the visual demo of it).

### Phase 7.2 · Deliverables finalize + README — `feat/26-runbook-deliverables`
- Goal: `RUNBOOK.md §demo` numbered click-through; finalize `EVALS/SECURITY/LICENSES`; real `README.md`.
- Done-when: a cold reader can boot and run the demo from the docs alone.

### Phase 7.3 · Demo prep + buffer — `feat/27-demo-prep`
- Goal: rehearse the demo; record; absorb slippage.
- Done-when: clean run-through within time; buffer consumed by overflow from earlier phases.

---

## PR template note

The committed `.github/pull_request_template.md` should list **terra-mind's** deliverables (ARCH / DECISIONS / RUNBOOK / EVALS / SECURITY / LICENSES) and the phase/branch/CI/no-secrets checklist — adapt the field names to this project, don't carry over labels that don't apply here.