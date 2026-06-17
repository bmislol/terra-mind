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

**Status:** **Phase 5.2 complete — Section 5 done (Sections 1–4 + 5.1 + 5.2 shipped).** Tenant isolation is now a **CI-gated fact**, not a claim. 4.1a built backend auth (`fastapi-users` argon2id user model on `tenants`, no migration; custom access(30 m)+refresh(30 d) JWTs; register/login/refresh/logout/guest; Redis-denylist revocation by `jti`, D-029; `/bot/ask` access-JWT gate; RLS context mechanism + **D-030** NULLIF fail-closed). **4.1b delivered:** short-term memory wired into `/bot/ask` (`app/memory/short_term.py` N=20/TTL=2 h, **D-031**, redaction-on-write) via the **two-short-transactions** RLS pattern (`app/services/memory.py`: resolve_session → agent with no DB held → record_turn, each re-setting `set_tenant_context`); **tenant isolation PROVEN end-to-end** through the real `/bot/ask` path as non-superuser `terramind_app` (`tests/services/test_rls_isolation.py` — under B's context, zero of A's rows); **conversation/data erasure** `DELETE /me` (**D-032**) proven physical via the owner connection (`tests/api/test_erasure.py`); `auth.login`/`session.revoked`/`tenant.erased` audit. **248/248 tests green** (real Postgres via testcontainers + fakeredis). **4.2 delivered (first C#):** fresh tModLoader mod in `client/TerraMind/` — `/bot` `ModCommand` reads live `Main.LocalPlayer` gear/inventory/stats + world flags (`NPC.downed*`) into the exact `StatePayload` JSON (explicit `[JsonPropertyName]` snake_case; `item.type`→`item_id`). **No CI for the mod** (ARCH §13.3) — **verified in-game across 7 `/bot test` runs** via `client.log` (gear/weapon/armor-split/defense/HP/prefixes/shape all track the real character); RUNBOOK §10 has build+verify steps. **4.3 delivered (mod = full authed chat client):** `/bot login <user> <pass>` (form-encoded `/auth/jwt/login`, password in-memory then discarded — chat-command **not** config, since `ModConfig` auto-persists; config holds the backend URL only, D-027 4.3 revision) → token pair persisted to `token.json` under `Main.SavePath` (tokens-only, no password) → restored on launch with a world-entry confirmation → **`/auth/refresh` on launch and on a 401** mints a fresh access JWT (durable past the 30-min TTL; shared `AuthFlow`) → **`/bot logout`** deletes `token.json` + denylists server-side (D-029). Authed `/bot/ask` renders the real `AskResponse` (`answer`+`session_id`, session threaded); **Ranger detected through the live path**. **No CI** (ARCH §13.3) — verified in-game across all 3 commits, evidence in `client/VERIFICATION.md` (the no-CI gate); rebuild **0 errors/0 warnings** after correcting the 4.2 nullable claim (csproj `<Nullable>` never reached the tML compile → per-file `#nullable enable`). **P-016 logged:** agent under-uses the always-sent live state on generic progression questions (Section 3/6 prompt/router tuning). **4.4 delivered (Section-4 payoff — end-to-end in-game):** the production chat surface verified as designed — **both router paths** fire from in-game (`routing=faq` for an item-effect lookup, `routing=agent` for hard progression Qs), the agent grounds **reliably** in live state, and an in-game turn yields **one clean Langfuse trace** (`bot.ask → router → agent/faq → rag.retrieve + llm`, with real token counts). **P-016 FIXED** by a contained `agent_system.md` grounding instruction (ground in the tool-provided live state every turn; never ask for lookupable state — chosen over raw-state injection, which would undercut D-026) — in-game after-pass: **3/3** reliable grounding + class-distinct melee↔ranger answers; broad cross-question measurement deferred to Section 6 (eval harness). Verified in-game (no CI, ARCH §13.3); evidence in `client/VERIFICATION.md` §4.4. **Carried:** memory `get_history` built-not-consumed; `DELETE /me` data-only (account deletion P-015); the 4.1b Docker CI run must be green before its PR merges. **Open polish (none blocking):** P-009, P-010, P-012, P-013, P-014. (P-016 fix-landed 4.4; broad measurement → S6.) **5.1 delivered (Section 5 — Web Surfaces):** **Part A backend** — three CI-tested additions over the Section-4 backend: **locked-origin CORS** (never `*`, tested), **`GET /versions`** (public corpus metadata), and **`tenant_preferences`** with the fail-closed `tenant_isolation` RLS policy (D-030 form — the **second** tenant-scoped type under DB-enforced RLS; a separate table, not a `tenants` column, which can't carry fail-closed RLS without breaking the pre-auth login lookups) + `GET`/`PATCH /me/preferences` (**255 tests green**). **Part B portal** — the React config portal (`frontend-user/`, Vite+React+TS): login/register/guest, version dropdown, prefs GET/PATCH (persist across reload), erasure-with-confirm; **token-only `localStorage`**, `401→/auth/refresh`; **erasure hidden for guests**; nginx bundle on `:5173` (compose `frontend-user`, `depends_on api`; api `start_period` 5s→150s for a clean cold `up` — **proven** via `down`+`up --build`). **D-011 revised** (polished portal). **D-032 extended:** erasure **RETAINS** preferences (account config). **Two-client model documented** (ARCH §13.2: portal & mod = separate clients/logins; guest is portal-only). **P-017:** stored `selected_version` not yet consumed by `/bot/ask` retrieval (storage + round-trip only). Verified in-browser (register → version → prefs persist → erasure → re-login prefs survived; guest path). Design-token SKILL unavailable → standard React/CSS defaults. **5.2 delivered (Streamlit operator/test bench — Section 5 done):** **Backend** — operator **bootstrap** (`app/entrypoints/bootstrap_operator`, idempotent create-or-promote to `is_superuser`; makes RUNBOOK §3 honest) + two **operator-only cross-tenant views** `GET /admin/tenants` + `GET /admin/audit-log` (`require_operator`-gated, **no tenant context** — `tenants`/`audit_log` have no RLS, **D-017 generalized to two data categories**: per-tenant content = fail-closed RLS, admin cross-tenant = role-gated; verified against the migrations). **Deferred:** `/admin/versions/check` (P-018), `/admin/rerag` button (P-019 — `build_corpus.py` script is the must-have). **Bench** — `frontend-admin/` Streamlit on `:8501` (server-side calls → no CORS): operator-gated (player blocked); **test chat** (the RUNBOOK §7.1 demo fallback) with 3 presets carrying **real Cargo item_ids** (melee 3507 / ranger 98 / mage 518 — class-distinct answers verified e2e) → `/bot/ask` → answer + routing + session_id + raw payload; versions/tenants/audit views. **259 tests green.** Compose `frontend-admin` real service; api `start_period` 150→**240s** (third false-alarm fixed, cold-boot-proven). Functional-not-polished; **UI polish for both web surfaces deferred to a later pass** (acknowledged choice). **Next: Section 6 — Security, Guardrails & CI** (guardrails + red-team set, CI eval gates — where P-016's broad measurement lands).

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
| Class detection (D-009 → D-026) | Hybrid: Cargo `damagetype` (446 weapons, gated on type=weapon) + curated armor map + LLM zero-shot cold-start; trained model confirmed not needed |
| Memory (D-010) | **Short-term Redis + TTL only**; no long-term memory |
| Frontends (D-011) | React `frontend-user/` (config portal) + Streamlit `frontend-admin/` (operator/test); no widget, no `demo/` |
| Guardrails (D-012) | Lightweight deterministic + LLM-judge filter; NeMo = stretch |
| Tracing (D-013) | Langfuse self-hosted in compose |
| Blob storage (D-014) | **No MinIO**; raw corpus on a gitignored volume |
| Tooling (D-015) | `uv`; ruff + format + mypy + pytest; conventional commits; one-phase-per-branch; refuse-to-boot |
| Version targets (D-016) | Terraria version = whatever tModLoader stable supports (confirm before scraping); .NET 8 SDK |
| Game-client auth (D-027 → P-005) | Mod login-once → discard password → persist refresh token → `/auth/refresh` → access JWT; registration portal-only |
| Backend URL (D-028 → P-011) | Mod reads URL from config, default `http://localhost:8000`; hosting = Section 7 stretch |
| Token model + revocation (D-029, TTLs D-006) | Custom access(30 min)+refresh(30 day) JWTs; Redis denylist keyed by `jti` (TTL = remaining life); logout/operator force-revoke; no rotation (P-014) |
| RLS context (D-030) | `set_config(..., true)` = SET LOCAL (transaction-local); policy `NULLIF(current_setting,'')::uuid` → fail-closed; set in services/ only. **Isolation PROVEN end-to-end in CI (4.1b)** |
| Short-term memory (D-031 → P-004) | Redis per-session list, N=20 / TTL=2 h (defended estimates); redaction-on-write; dual-write into `/bot/ask`; read path not yet consumed |
| Data erasure (D-032) | `DELETE /me` purges messages/sessions/Redis (RLS-scoped) + `tenant.erased` audit; **keeps the account row** (account/email deletion → P-015) |

**Open questions (graduate to D-NNN when settled, each with a number):** guardrail/red-team set (P-006), hybrid escalation (P-007); polish items — Langfuse token UI (P-009), cached agent graph (P-010), chunks_seen cap (P-012), nested agent spans (P-013), refresh rotation + reuse detection (P-014), full account deletion (P-015). _(Graduated: P-001→D-018, P-002→D-019, P-003→D-020, P-004→D-031, P-005→D-027, P-008→D-024, P-011→D-028.)_

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
- When a new module is imported, add it to `pyproject.toml` in the same edit. Don't rely on transitive inclusion.
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

Work is organized into **7 sections, 27 phases** (Section 4 split into 5 phases — 4.1a/4.1b/4.2/4.3/4.4 — in Section-4 planning), tracked granularly in `Checklist.md`. Each phase = one branch, one PR, CI green, merge, tick off.

- Section 1 — Foundations & Spike
- Section 2 — Corpus & RAG
- Section 3 — Router, Agent & Class Detection
- Section 4 — Auth & Game Client
- Section 5 — Web Surfaces
- Section 6 — Security, Guardrails & CI
- Section 7 — Polish & Present

Branch naming: `feat/<NN>-<slug>`, e.g. `feat/01-foundations`, `feat/07-wiki-scrape`, `feat/15-auth`.
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