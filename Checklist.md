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
> _Outline — expand into closeout lists when reached._

### Phase 3.1 · Classifier router — `feat/11-router`
- Goal: route easy FAQ → deterministic RAG; hard state-dependent → agent (ARCH §5 step 5).
- Touches: `app/services/router.py`, `app/prompts/`. Done-when: both paths exercised by a test.

### Phase 3.2 · Bounded agent + tools — `feat/12-agent`
- Goal: LangGraph bounded loop with `query_wiki`, `analyze_loadout`, `suggest_next_boss`; iteration cap (graduate P-008).
- Touches: `app/agent/`, `app/prompts/`, `DECISIONS`. Done-when: a hard query produces tool-grounded advice within the loop cap; trace shows the spans.

### Phase 3.3 · Live-state ingestion + class detection — `feat/13-state-class`
- Goal: state-payload schema; `analyze_loadout` infers class from equipped gear; LLM zero-shot cold-start fallback (D-009).
- Touches: `app/domain/`, `app/agent/`. Done-when: a mocked state payload yields correct class + progression-aware answer.

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