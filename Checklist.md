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
- [~] `CONTRIBUTING.md` at root.
- [~] Root `README.md` (stub; expanded later).
- [x] Commit drafted `deliverables/DECISIONS.md` and `deliverables/ARCH.md`.
- [x] Create empty `deliverables/{RUNBOOK,EVALS,SECURITY,LICENSES}.md` stubs.
- [x] `eval_thresholds.yaml` created with placeholder keys (values `PENDING`, filled in S2/S6).
- [~] Branch protection on `main` configured in GitHub UI.
- [x] All on `feat/01-foundations`; PR via template; squash merge; tick 1.1.

### Phase 1.2 · tModLoader spike — `feat/02-tmodloader-spike`
> Riskiest unknown first. Throwaway — proves the bridge, not a feature.
- [ ] Confirm tModLoader → Develop Mods detects the .NET 8 SDK (the one tonight's check covered).
- [ ] Minimal mod: read current HP from `Main.LocalPlayer`.
- [ ] Async `HttpClient` POST to a local FastAPI echo stub; print reply via `Main.NewText`.
- [ ] Round-trip works in singleplayer without freezing the game thread.
- [ ] Note findings (SDK quirks, API signatures) in `RUNBOOK.md`; tick 1.2.
- [ ] *If the spike fights back, this is the day to find out — re-scope before S4 if needed.*

### Phase 1.3 · Python tooling & FastAPI skeleton — `feat/03-python-tooling`
- [ ] `backend/app/` package tree per `ARCH.md §3` with `__init__.py`.
- [ ] `backend/pyproject.toml` (FastAPI, uvicorn, ruff, mypy, pytest) via `uv`; commit `uv.lock`.
- [ ] `app/main.py` with `/healthz`.
- [ ] `tests/test_healthz.py`.
- [ ] `.github/workflows/ci.yml` (lint/format/type-check/test).
- [ ] Local CI green; PR; CI green on PR; enable "Require status checks" on `main`; merge; tick 1.3.

### Phase 1.4 · Compose skeleton — `feat/04-compose-skeleton`
- [ ] `backend/Dockerfile`.
- [ ] `docker-compose.yml`: `db` (pgvector/pg16), `redis`, `vault`, `vault-init`, `langfuse`, `migrate`, `api`, `frontend-admin` + `frontend-user` stubs. (No minio/modelserver/widget/host — D-014, D-009, D-011.)
- [ ] `.env.example` with all non-secret config + secret placeholders.
- [ ] `docker compose up --build` → every service healthy; each `/healthz` 200.
- [ ] `down -v && up --build` → clean fresh boot second time.
- [ ] `RUNBOOK.md §1` (startup) + `ARCH.md §2` sanity-checked; tick 1.4.

### Phase 1.5 · Vault + Alembic + RLS scaffolding — `feat/05-vault-alembic-rls`
- [ ] `app/core/config.py`, `app/core/lifespan.py`, `app/infra/vault.py`.
- [ ] `scripts/vault-init.sh`; seeds `anthropic.api_key`, `jwt.signing_key`.
- [ ] Refuse-to-boot if Vault unreachable; `tests/test_refuse_to_boot.py`.
- [ ] ORM models: `tenants`, `sessions`, `messages`, `rag_chunks`, `audit_log` (no `memory_long` — D-010).
- [ ] Alembic init (async); first migration; `CREATE EXTENSION vector` added; **RLS policies** on tenant-scoped tables.
- [ ] `down -v && up --build`: vault-init seeds, migrate runs, tables + `vector` ext present; RLS verified (Tenant A can't read Tenant B).
- [ ] `ARCH.md §6/§9`, `SECURITY.md`; tick 1.5.

### Phase 1.6 · Langfuse + logging + redaction stub — `feat/06-langfuse-logging`
- [ ] `app/core/logging.py` (JSON), `app/infra/tracing.py`, `app/api/middleware.py` (request_id/trace_id/tenant_id contextvars).
- [ ] Refuse-to-boot if Langfuse unreachable.
- [ ] `/healthz` returns `X-Request-ID`; logs are structured JSON; trace visible in Langfuse UI.
- [ ] `app/infra/redaction.py` stub + `tests/test_logging.py` + redaction test.
- [ ] `ARCH.md §12`, `DECISIONS` (Langfuse config); tick 1.6.

---

## Section 2 — Corpus & RAG (Days 3–5)

Goal: a version-tagged wiki corpus in pgvector and a measured dense-retrieval baseline. Write the golden set **early** so it can't be skipped.

### Phase 2.1 · Wiki scrape — `feat/07-wiki-scrape`
- [ ] Confirm target Terraria version = tModLoader stable's supported version (D-016); record it.
- [ ] `scripts/scrape_wiki.py`: MediaWiki API, rate-limited, resumable cache → `data/raw/<version>/`.
- [ ] `manifest.json` with `raw_sha256`, page count, source, scraped_at.
- [ ] Attribution + license recorded in `LICENSES.md`; `ARCH.md §10`; tick.

### Phase 2.2 · Chunk + embed + corpus build — `feat/08-corpus-build`
- [ ] `scripts/build_corpus.py`: chunk (P-001 strategy), embed (MiniLM, local), upsert into `rag_chunks` tagged `game_version`.
- [ ] Idempotent re-run (upsert-keyed, no duplicates).
- [ ] Record chunk count + chosen chunking params → graduate P-001 to a `D-NNN`.
- [ ] `ARCH.md §11`; tick.

### Phase 2.3 · RAG golden set — `feat/09-rag-golden`
- [ ] 15 Terraria progression questions + expected source chunks → `data/eval/eval_rag.jsonl`.
- [ ] Spot-check answers exist in the corpus; `EVALS.md` documents the set; tick.

### Phase 2.4 · Dense retrieval + hit@k — `feat/10-rag-dense`
- [ ] `app/rag/pipeline.py`: dense-only, `game_version`-filtered (D-008).
- [ ] Eval harness; measure hit@k baseline → set thresholds in `eval_thresholds.yaml` (graduate P-003).
- [ ] `.github/workflows/eval-rag.yml` (manual dispatch; needs live DB).
- [ ] Decide hybrid escalation yes/no from the number (P-007); `DECISIONS`, `EVALS.md`; tick.

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