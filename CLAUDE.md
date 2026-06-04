# CLAUDE.md

Working guide for the AI assistant collaborating on this project. Read top-to-bottom before any session.

---

## 1. Project: terra-mind

A multi-tenant AI companion for Terraria. A player asks it questions from inside the game; it reads their live character/world state, retrieves the relevant Terraria wiki facts, and answers with progression-aware survival advice. Built **solo** as the AIE Program final project (target delivery 2026-06-18).

The companion:
- **Reads live game state** — equipped gear, inventory, defeated bosses, hardmode, biome — from a singleplayer C# tModLoader mod.
- **Routes** each question: easy wiki FAQ → a deterministic RAG flow; hard, state-dependent question → a bounded agent.
- **Answers** via RAG over a scraped, version-tagged Terraria wiki corpus in pgvector.
- **Detects class** by reading equipped gear (truthful), with an LLM zero-shot fallback for new characters.
- **Remembers** short-term within a game session (Redis, TTL). No long-term memory.

It runs across **three surfaces** over one FastAPI backend:
- **Game client (`client/`)** — singleplayer tModLoader mod. The **production chat surface**: `/bot <question>`.
- **React config portal (`frontend-user/`)** — login / guest / preferences / version selection / erasure. Not a chat surface.
- **Streamlit admin (`frontend-admin/`)** — operator/test bench: corpus & version management, re-rag, tenant view, test chat.

Tenant isolation is enforced by Postgres Row-Level Security; a short-lived JWT carries the `tenant_id` that sets the RLS context. The wiki corpus is shared and version-tagged; only player data is per-tenant.

---

## 2. Agent Directives & Current Status

**Execution Rule:** Always act as a technical planner first. For any non-trivial task, propose a step-by-step plan and wait for approval before writing code. Once approved, write the code.

**Status:** Phases 1.1–1.4 merged. **Phase 1.5 (Vault + Alembic + RLS) complete** — Vault secret loading, async SQLAlchemy, five ORM models, RLS policies on `sessions`/`messages`, refuse-to-boot test green. Pending manual boot test (`down -v && up --build`, RLS proof as `terramind_app`). **Phase 1.6 (Langfuse + logging + redaction)** is next. Eval thresholds remain `PENDING` until S2/S6.

Before suggesting any work, read these files in order:
1. `Checklist.md` — granular phase-by-phase progress; the source of truth for *what to build next*. **You maintain this file** — update it whenever a phase starts or finishes.
2. `deliverables/DECISIONS.md` — every architectural decision (D-001…) and open question (P-001…) with rationale and numbers.
3. `deliverables/ARCH.md` — system overview, layer rules, data flow, surfaces.
4. `deliverables/RUNBOOK.md` — startup, refuse-to-boot, eval running, demo flow (populated as phases land).
5. `eval_thresholds.yaml` — committed CI gates (values fill in during S2/S6).

---

## 3. Locked-In Decisions

Full rationale and numbers in `deliverables/DECISIONS.md`. Summary:

| Decision | Choice |
|---|---|
| Mode & surfaces (D-002) | Solo; SaaS backend demoed locally via compose; **singleplayer tModLoader client = production chat surface** |
| Layered backend (D-001) | `api / services / repositories / domain / infra / db` + `rag / agent / memory / guardrails / eval / prompts / core` |
| LLM provider (D-003) | Anthropic Claude only; `claude-haiku-4-5` default, `claude-sonnet-4-6` reserved (confirm availability) |
| Embedding model (D-004) | `all-MiniLM-L6-v2`, 384-dim, local → `vector(384)` |
| Vector store / corpus (D-005) | pgvector on Postgres 16; corpus **shared**, **version-tagged**; only player data is per-tenant |
| Tenancy (D-006) | Postgres RLS; JWT sets the tenant context |
| Secrets (D-007) | Vault + `vault-init`; real secrets only in uncommitted `.env`; `anthropic.api_key` + `jwt.signing_key` |
| Retrieval (D-008) | **Dense-only first**; hybrid only on measured underperformance; no HyDE |
| Class detection (D-009) | Live equipped-gear read + LLM zero-shot cold-start; trained model = future work |
| Memory (D-010) | **Short-term Redis + TTL only**; no long-term memory |
| Frontends (D-011) | React `frontend-user/` (config portal) + Streamlit `frontend-admin/` (operator/test); no widget, no `demo/` |
| Guardrails (D-012) | Lightweight deterministic + LLM-judge filter; NeMo = stretch |
| Tracing (D-013) | Langfuse self-hosted in compose |
| Blob storage (D-014) | **No MinIO**; raw corpus on a gitignored volume |
| Tooling (D-015) | `uv`; ruff + format + mypy + pytest; conventional commits; one-phase-per-branch; refuse-to-boot |
| Version targets (D-016) | Terraria version = whatever tModLoader stable supports (confirm before scraping); .NET 8 SDK |

**Open questions (graduate to D-NNN when settled, each with a number):** chunking (P-001), pgvector index (P-002), RAG thresholds (P-003), Redis TTL (P-004), **game-client identity (P-005)**, guardrail/red-team set (P-006), hybrid escalation (P-007), agent loop cap (P-008).

---

## 4. Project Rules (graded — do not violate)

1. **No vibe coding.** Every line shipped is understood, every library justified. The defense will ask.
2. **The architecture is the grade.** Layer boundaries respected (`ARCH.md §4`), secrets in Vault, traces visible, logs redacted, exceptions handled.
3. **Tenant isolation is the security story.** RLS enforced at the DB; a query can never cross `tenant_id`. The wiki corpus is the one shared, intentionally non-tenant-scoped resource.
4. **The evals are the grade.** CI must be green before merge. A regression must turn the build red. The red-team set must pass (0 successful injections) for a green build.
5. **Every decision is backed by a number.** Embedding choice, chunking, retrieval, thresholds — every choice in `DECISIONS.md` cites a number on a golden set. Numbers that don't exist yet are marked `PENDING (measure)`, never guessed.
6. **Logs are redacted, traces are real.** A redaction test proves the first; a Langfuse trace tree proves the second.

---

## 5. Engineering Conventions

- `uv` for packaging; `uv lock && uv sync` after dep changes.
- ruff + ruff format + mypy + pytest all green locally before pushing.
- mypy: pin every `# type: ignore` to a specific code (e.g. `[no-untyped-call]`), never blanket.
- Squash merge always; conventional commits (one-line summary + body).
- Decisions written to `deliverables/DECISIONS.md` as the work happens, in the same PR.
- Refuse-to-boot: `api` crashes early if Vault, Langfuse, or eval thresholds are misconfigured.
- Secrets in Vault: `secrets.anthropic.api_key`, `secrets.jwt.signing_key`. Never in env or code.
- Models: `claude-haiku-4-5` (router/agent default — latency matters for live advice), `claude-sonnet-4-6` (reserved for harder reasoning).

**Don't do:**
- Don't introduce OpenAI or any other LLM provider (D-003).
- Don't add `tenant_id` to the wiki corpus — it's shared by design (D-005).
- Don't add long-term / cross-conversation memory (D-010).
- Don't re-introduce dropped services: MinIO, a modelserver, or the widget/host embed stack (D-009, D-011, D-014).
- Don't add a per-line `# type: ignore` without a specific code.
- Don't push without local CI green.
- Don't write `# TODO: figure out later` — finish the phase or log an explicit deferral in `DECISIONS.md`.

---

## 6. Repository Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── api/             # HTTP routers, schemas, route dependencies
│   │   ├── services/        # Business logic, transaction boundaries, RLS context, router orchestration
│   │   ├── repositories/    # SQL via async SQLAlchemy (under the RLS context)
│   │   ├── domain/          # Pydantic domain models, enums, contracts
│   │   ├── infra/           # Vault, Redis, LLM, tracing, redaction, embedding client
│   │   ├── db/              # ORM models, sessions, Alembic migrations, RLS policies
│   │   ├── rag/             # Chunking, retrieval, version filtering
│   │   ├── agent/           # Bounded LangGraph loop, tool registry, prompt loading
│   │   ├── memory/          # Short-term (Redis) session memory
│   │   ├── guardrails/      # Input/output filter, red-team set, LLM-judge
│   │   ├── eval/            # Golden sets, eval harnesses
│   │   ├── prompts/         # Versioned prompt files
│   │   └── core/            # Config, logging, lifespan, shared errors
│   ├── scripts/             # scrape_wiki.py, build_corpus.py, vault-init.sh
│   └── data/                # gitignored — raw scrape + built corpus per version
├── frontend-admin/          # Streamlit operator/test bench
├── frontend-user/           # React + Vite config portal
├── client/                  # C# tModLoader mod (production chat surface)
├── deliverables/            # ARCH, DECISIONS, RUNBOOK, EVALS, SECURITY, LICENSES
├── .github/workflows/       # ci.yml, eval-rag.yml, eval-redteam.yml
├── docker-compose.yml
├── .env.example
├── eval_thresholds.yaml
├── Checklist.md
└── CLAUDE.md
```

The full layer-by-layer rule table is in `deliverables/ARCH.md §4`.

---

## 7. Phase Breakdown

Work is organized into **7 sections, 25 phases**, tracked granularly in `Checklist.md`. Each phase = one branch, one PR, CI green, merge, tick off.

- Section 1 — Foundations & Spike
- Section 2 — Corpus & RAG
- Section 3 — Router, Agent & Class Detection
- Section 4 — Auth & Game Client
- Section 5 — Web Surfaces
- Section 6 — Security, Guardrails & CI
- Section 7 — Polish & Present

Branch naming: `feat/<NN>-<slug>`, e.g. `feat/01-foundations`, `feat/07-wiki-scrape`, `feat/14-auth`.
Commit style: conventional commits.
PR template: `.github/pull_request_template.md` (added in Phase 1.1).

`Checklist.md` holds full closeout checklists for near-term phases and outlines for later ones; outlines are expanded into closeout lists as each phase is reached.

---

## 8. Working Style (for the agent)

- **No vibe coding.** Every change explained, every library justified. If unsure why a line exists, stop and ask.
- **One phase per branch.** Don't bleed across phases; if scope creep appears, open a new branch.
- **Commit small, commit often.** Conventional commits.
- **Update deliverables in the same PR as the code.** Decisions are written when made.
- **CI must be green before merging.** Don't bypass.
- **Ask before architectural changes.** Layer rules are graded — moving logic across layers is a decision, not a refactor.
- **Resolve the relevant `P-NNN` when its phase lands**, and graduate it to a `D-NNN` with its number.

---

## 9. Daily Quickstart

1. Pull `main`, confirm CI green.
2. Open the current section in `Checklist.md`.
3. Pick the next unticked phase; create its branch (`feat/<NN>-<slug>`).
4. Read the relevant `deliverables/` section(s) and any `P-NNN` the phase resolves.
5. Work the phase. Commit. Push. Open the PR via the template.
6. Wait for CI green. Squash merge. Tick the phase in `Checklist.md` and update `CLAUDE.md §2` status.