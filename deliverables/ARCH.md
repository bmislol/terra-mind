# ARCH.md

Project: terra-mind
Last updated: 2026-06-03

> **Status note.** This is a day-zero architecture document: it describes the **target** design. Sections describing flows not yet built are marked _Status: design_. As phases land, the relevant section's date and status are updated in the same PR (per D-015).

## 1. System Overview

terra-mind is a multi-tenant AI companion for Terraria. A player asks it questions from inside the game; it reads their live character/world state, retrieves the relevant Terraria wiki facts, and answers with progression-aware survival advice. It runs as a SaaS backend, demoed locally via `docker compose` (D-002).

There are **three surfaces** over one FastAPI backend:

- **Game client (`client/`)** — a singleplayer C# tModLoader mod. **This is the production chat surface.** The player types `/bot <question>`; the mod packages live player/world state and the question, calls the backend, and renders the reply in the in-game chat. (Substitutes the embeddable web widget from the original brief.)
- **React config portal (`frontend-user/`)** — login / guest / preferences / version selection / right-to-erasure. It configures the player's account; **it is not a chat surface.**
- **Streamlit admin (`frontend-admin/`)** — operator/test bench: corpus and version management, re-rag trigger, tenant view, and a test chat for exercising the `/bot` flow without the game.

Tenant isolation is enforced by Postgres Row-Level Security; a short-lived JWT carries the `tenant_id` that sets the RLS context per request (D-006). The wiki corpus is shared and version-tagged; only player data is per-tenant (D-005).

### 1.1 Flow of the Final Product

```text
        PLAYER (in game)                OPERATOR / TEST                 PLAYER (account mgmt)
        ================                ===============                 =====================
   Terraria + tModLoader mod        localhost:8501 (Streamlit)      localhost:5173 (React portal)
        /bot <question>             corpus/version mgmt, re-rag      login/guest, prefs, version,
              │                     trigger, tenant view, test chat   right-to-erasure
   reads live state JSON                     │                              │
   (gear, inventory, downed                  │                              │
    bosses, hardmode, biome,                 │                              │
    selected version)                        │                              │
              │                              │                              │
   exchange id → short-lived JWT             │                              │
              └──────────────┬───────────────┴──────────────────────────────┘
                             ▼
                  FastAPI backend (localhost:8000)
                  JWT → RLS tenant context
                             │
                   guardrails: input check
                             │
                   CLASSIFIER ROUTER
                   ┌─────────┴───────────┐
                   ▼                     ▼
            easy FAQ →            hard state-dependent →
            deterministic RAG     bounded LangGraph agent
                   │              tools: query_wiki,
                   │              analyze_loadout,
                   │              suggest_next_boss
                   └─────────┬───────────┘
                             ▼
        ┌────────────────────┼─────────────────────┐
        ▼                    ▼                      ▼
   pgvector RAG         Redis (short-term      guardrails: output
   shared corpus,        session memory,        check
   version-filtered      TTL)
                             │
                   single JSON reply → mod renders via Main.NewText
```

Every turn is one Langfuse trace: the player message at the root, the router decision, each agent tool call as a child span, the LLM call with token counts, and the retrieved chunks. Every log line carries the trace ID. Redaction strips secrets before anything leaves the service boundary (§12.3).

## 2. Main Runtime Services

| Service | Purpose |
|---|---|
| `api` | FastAPI application: auth + token exchange, RLS tenant context, classifier router, agent, RAG, short-term memory, guardrails, version/corpus admin. |
| `frontend-admin` | Streamlit operator/test bench (§13.1). |
| `frontend-user` | React + Vite config portal, served static (§13.2). |
| `migrate` | Runs `alembic upgrade head` and exits before `api` boots. |
| `worker` | RQ worker (`rq worker rerag`) on the existing Redis — runs the operator-triggered corpus re-rag as a background job (D-033). Same image as `api`; `DATABASE_URL` + the data volume (RW) + Redis, **no Vault**. Runs independently of `api` (a re-rag survives an `api` restart). |
| `db` | Postgres 16 with `pgvector`. Tenant data + the shared, version-tagged wiki corpus. |
| `redis` | Redis 7 for short-term session memory (TTL), the JWT denylist, and the RQ re-rag broker + single-job lock + live-progress hash (D-033). |
| `vault` | HashiCorp Vault (dev mode) for runtime secret resolution. |
| `vault-init` | Seeds Vault KV paths from env and exits. |
| `langfuse` | Self-hosted Langfuse for trace storage and the trace-tree UI. |

The **game client (`client/`) is not a compose service** — it runs inside Terraria/tModLoader on the host and talks to `api` over HTTP.

### 2.1 Intentionally Absent

These were **deliberately dropped** for terra-mind; their absence is a decision, not an omission:

- `minio` — no model artifacts to store; raw corpus lives on a gitignored volume (D-014).
- `modelserver` — the trained class predictor is future work; class detection is live gear-read + LLM zero-shot (D-009).
- `widget`, `host`, `blocked-host` — the game client replaces the embeddable web widget, so the CORS/`frame-ancestors` embed demo no longer exists (D-011).
- Long-term cross-conversation memory and its `memory_long` table + audit-logged writes (D-010).

## 3. Repository Layout

```text
.
├── backend/
│   └── app/
│       ├── api/             # HTTP routers, request/response schemas, route dependencies
│       ├── services/        # Business logic, transaction boundaries, RLS context, router orchestration
│       ├── repositories/    # SQL-only data access via async SQLAlchemy
│       ├── domain/          # Pydantic domain models, enums, internal contracts
│       ├── infra/           # Adapters: Vault, Redis, LLM provider, tracing, redaction, embedding client
│       ├── db/              # SQLAlchemy ORM models, sessions, Alembic migrations, RLS policies
│       ├── rag/             # Chunking, retrieval, query transformation, version filtering
│       ├── agent/           # Bounded LangGraph loop, tool registry, prompt loading
│       ├── memory/          # Short-term (Redis) session memory adapter
│       ├── guardrails/      # Input/output filter, red-team rule set, LLM-judge
│       ├── eval/            # Golden sets, eval harnesses (RAG hit@k, red-team)
│       ├── prompts/         # Versioned prompt files
│       └── core/            # Config, logging, startup/lifespan, shared errors
│   ├── scripts/             # scrape_wiki.py, build_corpus.py (offline pipeline), vault-init.sh
│   └── data/                # gitignored — raw scrape + built corpus per version
├── frontend-admin/          # Streamlit operator/test bench
├── frontend-user/           # React + Vite config portal (single bundle)
├── client/                  # C# tModLoader mod (production chat surface)
├── deliverables/            # ARCH, DECISIONS, RUNBOOK, EVALS, SECURITY, LICENSES
├── .github/workflows/       # ci.yml, eval-rag.yml, eval-redteam.yml
├── docker-compose.yml
├── .env.example
├── eval_thresholds.yaml
├── Checklist.md
└── CLAUDE.md
```

## 4. Layer Boundary Rules

This boundary is graded. Expect to be asked to add a new endpoint or agent tool live.

| Layer | Owns | Must Not Do |
|---|---|---|
| `app/api/` | HTTP concerns only: routers, status codes, request/response models, auth dependencies. | No SQLAlchemy queries, no Redis calls, no Vault calls, no LLM calls, no setting RLS context directly. |
| `app/services/` | Business rules, transaction boundaries, **setting the per-request RLS tenant context**, router decision, agent orchestration, guardrail invocation, audit writes. | No `HTTPException` as business logic, no FastAPI `Request` dependency. |
| `app/repositories/` | SQL reads/writes through async SQLAlchemy sessions (operating under the RLS context the service set). | No cache invalidation, no HTTP errors, no external systems, no business decisions. |
| `app/domain/` | Pydantic domain models, enums, service/repository contracts. | No database sessions, no HTTP concepts, no external clients. |
| `app/infra/` | Adapters for Vault, Redis, LLM provider, Langfuse, redaction, embedding model client. | No business rules beyond adapter-level error wrapping. |
| `app/db/` | ORM models, session factory, Alembic migrations, **RLS policy definitions**. | Imported only by repositories and DB setup code. |

## 5. Core Data Flow: One `/bot` Turn

_Status: partial. Steps 3 (RLS context), 5, 6, 7, 8, 10–11 implemented; the mod (1–2) is Phase 4.2+, guardrails (4, 9) are Phase 6.1._

1. In game, the player types `/bot <question>`. The mod (`client/`) collects a **state payload** (`StatePayload`, finalized Phase 3.3): `gear` (`armor` / `accessories` / `weapon`, each an `ItemRef{item_id, name, prefix, stack}`), `inventory: list[ItemRef]`, `stats` (`PlayerStats{life, max_life, mana, max_mana, defense}`), `world` (`hardmode`, `downed_bosses: list[str]`, `biome`), and the tenant's selected `game_version`. `item_id` (= Terraria `item.type` = Cargo `itemid`) is the canonical gear key; `name` is for readability. _(Schema implemented Phase 3.3; mod producer Phase 4.2)_
2. The mod presents its saved refresh token (see §6 / D-027) to `POST /auth/refresh` and receives a short-lived access JWT. It POSTs `{message, state, session_id?}` to `POST /bot/ask` with the Bearer token. _(`/auth/refresh` implemented Phase 4.1a; mod producer Phase 4.3)_
3. `app/api/bot.py` authenticates via the access-JWT dependency; the **service** sets the **RLS tenant context** (`set_tenant_context`, SET LOCAL) from the JWT's `tenant_id` before each tenant-scoped transaction. _(Phase 4.1a/4.1b — **implemented**; D-030)_
4. **Guardrails input check** (`app/guardrails/`): block prompt-injection / progression jailbreaks ("give me dev items") before any LLM call. _(Phase 6.1 — design)_
5. **Classifier router** (`app/services/router.py`): an easy FAQ ("Copper Shortsword recipe?") goes to a deterministic RAG flow; a hard, state-dependent query ("why do I keep dying to Skeletron?") goes to the agent. _(Phase 3.1 — **implemented**; single LLM call to `claude-haiku-4-5`, D-023)_
6. **Bounded agent** (`app/agent/`, LangGraph): runs up to **MAX_ITERATIONS = 5** plan→execute cycles (D-024) over three tools — `query_wiki` (RAG, version-filtered, D-008), `analyze_loadout` (reads the state payload; hybrid Cargo `damagetype` + curated armor map + LLM zero-shot cold-start fallback per D-026, implementing D-009), `suggest_next_boss` (deterministic progression tree). The loop is `plan → (execute_tools | END)`; `execute_tools → (plan | synthesize_cap)` when the cap is hit. One iteration can dispatch multiple tools (D-024 caveat). _(Phase 3.2 — **implemented**; `app/agent/graph.py` + `app/services/agent.py`; replaces the 3.1 stub. Cost/latency profile in D-025.)_
7. **RAG retrieval** (`app/rag/`): dense query against the shared corpus, filtered to the tenant's selected `game_version` (D-005, D-008). _(Phase 2.4 — **implemented**; `app/rag/pipeline.py`, dense-only, HNSW)_
8. **Short-term memory** (`app/memory/`, `app/services/memory.py`): the service resolves/creates the session (txn 1) and, after the answer, **records the turn** to Postgres `messages` (RLS-scoped) + the Redis list (txn 2), redacted, N=20/TTL=2 h (§8, D-031). The agent runs between the two short transactions with no DB held. The Redis **read** (`get_history`) is built but not yet consumed (§8). _(Phase 4.1b — **implemented**)_
9. **Guardrails output check**: scan the drafted reply before it leaves the boundary. _(Phase 6.1 — design)_
10. The whole turn runs under one Langfuse trace opened per request by `RequestContextMiddleware`; router, RAG, and LLM calls are child spans. _(Phase 3.1 — **implemented**; trace tree verified: `http_request → bot.ask → router.classify → router.llm / faq.answer → rag.retrieve + faq.llm`)_
11. `POST /bot/ask` returns a **single JSON reply** (the game chat renders one message via `Main.NewText` — SSE streaming into a game chat line is unnecessary here; the Streamlit test chat in §13.1 may stream for development convenience). _(Phase 3.1 — **implemented**; `app/api/bot.py`, no auth gate yet)_

## 6. Authentication, Authorization & Tenancy

_Status: **implemented Phase 4.1a** — register/login/refresh/logout/guest, the access+refresh token model + Redis denylist, the access-JWT gate on `/bot/ask`, and the RLS-context mechanism (built + proven). The full two-tenant product-isolation proof + auth audit events land in 4.1b._

**Library:** `fastapi-users[sqlalchemy]` for the **user model + password hashing (argon2id) + register**, bound to the existing `tenants` table (no migration). Token **issuance/verification is custom** (`app/infra/jwt_tokens.py`, pyjwt HS256) because the access+refresh split needs custom claims (`tenant_id`/`role`/`jti`/`type`) + a denylist that fastapi-users' `JWTStrategy` does not model.

**JWT signing key:** resolved from Vault at lifespan startup (`secrets.jwt.signing_key`, `HS256`). Read from `request.app.state` at request time — never from a module import or env var.

**Token model (D-029, D-006):** login returns `{access (30 min), refresh (30 day)}`. The **access** token (claims `sub`=tenant_id, `role`, `jti`, `type=access`) is the only token that authorizes resource endpoints and is the RLS-context source; the **refresh** token only mints access at `POST /auth/refresh`. Guests are access-only. Both TTLs server-pinned.

**RLS context — set in services/ only (D-030, ARCH §4):** the request's service sets the tenant context with `set_config('app.current_tenant_id', <tenant_id>, true)` (`SET LOCAL`, transaction-local) **before any tenant-scoped query**; the RLS policies then filter to that tenant. The policy uses `NULLIF(current_setting(...), '')::uuid` so an uncontexted/pooled-revert connection fails **closed** (zero rows, no error). The mechanism is built and proven (`tests/services/test_rls_context.py`, non-superuser role); it is invoked at the first tenant-scoped op — **not** in `/bot/ask`, which currently runs no tenant-scoped query (`rag_chunks` is shared, D-005). `/bot/ask` is auth-gated and carries the authenticated `tenant_id`.

**Tenant model:** a tenant is a **player account** (or a guest). Every player-data row carries `tenant_id`; the access JWT carries it; the service layer sets it as the RLS context. The wiki corpus is **not** tenant-scoped (D-005).

**Registration:** players **self-register** through the React portal (D-011). **No email verification, no password reset** (cut — see brief; zero grading value, live-demo failure risk). **Guest mode** = an ephemeral tenant with a TTL and no persistence; erasure is a no-op for guests.

**Game-client identity & mod login (D-027, resolves P-005):** the mod authenticates as a player account via **login-once / token-persist**:
1. A **`/bot login <user> <pass>` chat command** sends username + password → `POST /auth/jwt/login` → the mod **discards the password immediately** (in-memory for that one call, never stored). The mod config holds the **backend URL only** (D-028), no credentials — a `ClientSide` `ModConfig` auto-persists to disk, so config-held creds would be a plaintext password on disk.
2. The returned **refresh** token is saved as `token.json` under the tModLoader save dir (`<save>/TerraMind/`, **tokens only — no password**); each launch the mod exchanges it at `POST /auth/refresh` for a **short-lived access JWT** (`tenant_id` + role — the RLS-context source), and a mid-session 401 triggers the same refresh. Stay-logged-in across restarts. (`/client/token` was folded into `/auth/refresh`, D-027/D-029.)
3. `/bot logout` deletes the saved token locally **and** denylists it server-side (D-029).
Registration is **portal-only** (D-011), never via the mod. Backend URL is config-driven, default `http://localhost:8000` (D-028). The mod holds **no password and no API key** — only a revocable token; HTTPS is required for the one password transmission in any hosted deployment (SECURITY §4).

**Session revocation (D-029):** logout (and operator force-revoke) adds the JWT's `jti` to a **Redis denylist** with TTL = the token's remaining lifetime. `POST /auth/logout` denylists the refresh token's `jti`; `POST /auth/refresh` and the access-token gate check the denylist before honoring a token; `audit_log` records the `session.revoked` event (durable trail). Redis is reused from the memory tier (D-010) — no new service, self-expiring entries.

**Role model:** `is_superuser: bool` on `tenants`:

| Role | `is_superuser` | Permissions |
|---|---|---|
| `player` | `False` | Play via the mod, configure own profile, select version, set prefs, erase own data. |
| `operator` | `True` | All player perms + manage corpora, trigger re-rag, view tenants, use the admin test chat. |

First operator is bootstrapped via a script (RUNBOOK §3).

## 7. Endpoint Inventory

_Status: auth + `/bot/ask` gating landed Phase 4.1a; `/versions` + `/me/preferences` (GET/PATCH) landed **Phase 5.1** (+ a locked-origin CORS allow-list, never `*`); `/admin/tenants` + `/admin/audit-log` landed **Phase 5.2**; `/admin/rerag` + `/admin/rerag/status/{id}` landed **Phase 5.3** (reverses P-019 → D-033). `/admin/versions/check` still deferred (P-018). Phase tags in Notes column._

| Method | Endpoint | Roles | Notes |
|---|---|---|---|
| `POST` | `/auth/register` | Public | Player self-registration (no email verification); **privilege-safe** (strips `is_superuser` — no self-elevation). Portal-only (D-011, D-027). **Implemented Phase 4.1a.** |
| `POST` | `/auth/jwt/login` | Public | username/password → `{access_token, refresh_token}` (D-029). The mod calls this once, then discards the password (D-027). **Implemented Phase 4.1a.** |
| `POST` | `/auth/refresh` | Public (refresh token) | Exchange a valid, non-denylisted **refresh** token for a new access token. **This is the mod's saved-token exchange** — `/client/token` was folded in here (D-027/D-029). Rejects access-type / expired / denylisted tokens (401). **Implemented Phase 4.1a.** |
| `POST` | `/auth/logout` | Player | Denylist the **refresh** token's `jti` (D-029) + `session.revoked` audit row; the mod also deletes its saved token. **Implemented Phase 4.1a.** |
| `POST` | `/auth/guest` | Public | Create an ephemeral guest tenant; returns an **access-only** token (no refresh — guests are ephemeral). **Implemented Phase 4.1a.** |
| `GET` | `/healthz` | Public | Liveness probe. _(implemented Phase 1.3)_ |
| `POST` | `/bot/ask` | Player (**access JWT**) | Send `{message, state, session_id?}`; returns `{answer, source_chunks, routing, session_id}`. **Phase 4.1b:** the service resolves/creates the session, runs routing, and records the turn (Postgres under RLS + Redis) via the two-short-transactions pattern. Gated by the access-JWT dependency (4.1a). Router 3.1, agent 3.2, class detection 3.3. |
| _(dropped)_ | ~~`/client/token`~~ | — | **Removed (D-027/D-029):** the access+refresh split makes the mod's saved-token exchange identical to `/auth/refresh`; folded in there. |
| `GET` | `/versions` | **Public** | List the shared corpus's distinct `game_version` values (D-005 — shared corpus metadata, not tenant data, so no token; powers the portal dropdown). **Implemented Phase 5.1.** |
| `GET` | `/me/preferences` | Player (**access JWT**) | Read own preferences; **RLS-scoped** via the `tenant_preferences` table (fail-closed policy, D-011 revision / Option 2). **Implemented Phase 5.1.** _(stored `selected_version` is NOT yet consumed by `/bot/ask` retrieval — P-017.)_ |
| `PATCH` | `/me/preferences` | Player (**access JWT**) | Upsert own preferences (RLS-scoped). **Implemented Phase 5.1.** |
| `DELETE` | `/me` | Player (access JWT) | **Conversation/data erasure (D-032), implemented Phase 4.1b** — purges the tenant's `messages`/`sessions` (RLS-scoped DELETE) + Redis history keys + a `tenant.erased` audit row. **Keeps the account row** (full account/email deletion → P-015). |
| `GET` | `/admin/tenants` | operator (**`require_operator`**) | List all tenants (id/email/is_guest/created_at). **Cross-tenant** read, NOT RLS-scoped — `tenants` has no RLS (D-017); the gate is the control. **Implemented Phase 5.2.** |
| `GET` | `/admin/audit-log` | operator (**`require_operator`**) | Recent audit events (`tenant.erased`/`auth.login`/`session.revoked`/`corpus.reragged`, SECURITY §6). Cross-tenant read of the non-RLS `audit_log` (D-017). **Implemented Phase 5.2.** |
| `GET` | `/admin/versions/check` | operator | Newer-than-stored wiki check. **Deferred (P-018)** — live-wiki compare, ~zero demo value; the admin view lists stored versions via `GET /versions`. |
| `POST` | `/admin/rerag` | operator (**`require_operator`**) | Start a corpus re-rag as a **background job** (D-033, reverses P-019): acquire the single-job lock → enqueue on RQ → `202 {job_id, status}`; **409** if one is already running (no queue). **Implemented Phase 5.3.** |
| `GET` | `/admin/rerag/status/{job_id}` | operator (**`require_operator`**) | Poll a re-rag job: the durable `rerag_jobs` row (status/timestamps/error) + the freshest live progress (stage/done/total) overlaid from Redis. `404` if unknown. **Implemented Phase 5.3.** |

## 8. Memory Plan

### 8.1 Short-Term (Redis) — the only memory tier

_Status: **implemented Phase 4.1b.**_ Per-session message history as a Redis list under `session:{tenant_id}:{session_id}:messages`; each element a JSON `{"role", "content"}`.

- **Window / TTL:** N=20 messages (`RPUSH` + `LTRIM`), TTL=2 h sliding `EXPIRE` — **D-031** (defended estimates, config-overridable; graduates P-004).
- **Module:** `app/memory/short_term.py` — `append_message`, `get_history`, `clear`. Redis client **injected** (no global import). `content` is **redacted before the write** (SECURITY §7.1).
- **Dual-write into `/bot/ask`:** the turn is persisted to **both** Postgres `messages` rows (RLS-scoped — the per-tenant data the isolation proof operates on) and the Redis list, orchestrated by `app/services/memory.py` using the **two-short-transactions** pattern: `resolve_session` (txn 1, sets RLS context) → agent/FAQ runs with **no DB transaction held** → `record_turn` (txn 2, re-sets context). `set_config(..., true)` is `SET LOCAL` (per-transaction), so each tenant-scoped txn re-sets the context (D-030).
- **Read path built-but-not-yet-consumed (by design):** `get_history` is implemented and tested but **not** loaded into `/bot/ask`'s request path — the agent doesn't consume conversational history yet, and adding a hot-path read with no consumer would be hollow plumbing. It wires to a consumer (agent memory / a history endpoint) in a later phase. Written-but-not-yet-read is intentional, not dead code.

### 8.2 Long-Term — intentionally none

There is **no** cross-conversation / long-term memory (D-010). Survival advice is session-scoped; there is no product need to recall prior sessions. This absence is graded as a scoping decision, not a missing feature.

## 9. Startup and Refuse-to-Boot Checks

Compose boot sequence:

1. `vault` starts in dev mode.
2. `vault-init` seeds Vault KV paths and exits.
3. `db`, `redis`, `langfuse` start.
4. `migrate` runs `alembic upgrade head` (incl. `CREATE EXTENSION vector` and RLS policies) and exits.
5. `api`, `frontend-admin`, `frontend-user` start.

`api` refuses to boot if any of:
- Vault is unreachable.
- The Langfuse tracing backend is unreachable or rejects credentials.
- Any committed eval threshold in `eval_thresholds.yaml` is zero or missing.

There is no `modelserver` refuse-to-boot check (no trained model artifact in scope; D-009).

_Phase 1.5: Vault refuse-to-boot implemented (`app/infra/vault.py`). Phase 1.6: Langfuse refuse-to-boot and eval-threshold refuse-to-boot implemented (`app/core/lifespan.py`). Eval-threshold `PENDING` values pass the check intentionally; real numbers fill in during S2/S6._

## 10. Wiki Scraping & Corpus-Build Contract

_Status: Phase 2.1 implemented (`feat/07-wiki-scrape`). Phase 2.2 implemented (`feat/08-corpus-build`)._

Terra-mind's offline pipeline is the wiki ingest, not model training.

The corpus is built **offline** by three host-side scripts in sequence, never from a request:

```text
backend/scripts/scrape_wiki.py      # MediaWiki API — writes data/raw/<version>/pages/*.json
backend/scripts/scrape_cargo.py     # Cargo API (Items + Recipes) — writes data/raw/<version>/cargo/
backend/scripts/build_corpus.py     # chunk → embed (MiniLM) → upsert into pgvector, tagged game_version
backend/data/raw/<game_version>/    # gitignored raw snapshot
```

**Invocation sequence (RUNBOOK.md §4):**
```
uv run python -m scripts.scrape_wiki  --version 1.4.4.9
uv run python -m scripts.scrape_cargo --version 1.4.4.9
uv run python -m scripts.build_corpus --version 1.4.4.9
```

---

### scrape_wiki.py (Phase 2.1)

**API base:** `https://terraria.wiki.gg/api.php` · Namespace: 0 (Main) only · Format: wikitext · Batch: 50 pages/request · Rate: 1 batch/second

**Discovery runs on every invocation** (cost: ~10 API calls, ~10 s). Symmetric diff: new / unchanged / disappeared. Disappeared pages moved to `.checkpoint/orphaned/`. Print `New: N  Unchanged: M  Disappeared: K` before fetching.

**Resumability:** per-page atomic writes (`os.replace`); crashed runs resume from existing `pages/<page_id>.json` files. Retry-exhausted pages → `.checkpoint/failed.jsonl`; no manifest write until complete.

**Per-page schema** (`pages/<page_id>.json`): `page_id`, `title`, `namespace`, `revision_id`, `timestamp`, `source_url` (from API `canonicalurl`), `wikitext`, `is_disambiguation`. This is the 2.1 → 2.2 contract; do not change after merge without a revision note.

---

### scrape_cargo.py (Phase 2.2)

**Tables:** `Items` (6,233 rows, 32 fields fetched) and `Recipes` (4,221 rows, 7 fields fetched). No other tables — NPCs, Drops, History, etc. are out of scope (see DECISIONS.md D-018).

**Pagination:** `action=cargoquery&limit=500&offset=N` — ~13 requests for Items, ~9 for Recipes. Rate: 1 request/second.

**Resumability:** if `cargo/items.json` and `cargo/recipes.json` both exist and `manifest.json` already has `cargo_raw_sha256`, the script exits cleanly (idempotent). `--force` clears `cargo/` and re-fetches. Partial or failed fetches: non-zero exit, no manifest write.

**Output layout:**
```
data/raw/1.4.4.9/
    cargo/
        items.json               # JSON array of Items Cargo rows
        recipes.json             # JSON array of Recipes Cargo rows
        orphan_recipes.jsonl     # Recipes rows with no matching wiki page
```

**Join keys:**
- `items.json`: `row["_pageName"]` matches `page["title"]` exactly.
- `recipes.json`: `row["result"]` matches `page["title"]`. (`_pageName` is the recipe register page, not the item page — do not use it as the join key.)

---

### Manifest (`manifest.json`) — full schema

```json
{
  "game_version":       "1.4.4.9",
  "source":             "https://terraria.wiki.gg",
  "api_base":           "https://terraria.wiki.gg/api.php",
  "scraped_at":         "<ISO-8601>",
  "page_count":         5157,
  "raw_sha256":         "<hex>",
  "cargo_scraped_at":   "<ISO-8601>",
  "cargo_raw_sha256":   "<hex>",
  "cargo_table_counts": {"items": 6233, "recipes": 4221},
  "chunk_count":        22173,
  "embedding_model":    "sentence-transformers/all-MiniLM-L6-v2",
  "embedding_dim":      384
}
```

`raw_sha256` — SHA-256 over all page wikitexts in ascending `page_id` order. Written by `scrape_wiki.py`.
`cargo_raw_sha256` — SHA-256 over `items.json` bytes + `\x00` + `recipes.json` bytes. Written by `scrape_cargo.py`.
`chunk_count`, `embedding_model`, `embedding_dim` — written by `build_corpus.py`.
All three scripts fail loudly and leave the manifest in a deterministically incomplete state if they crash.

---

### build_corpus.py (Phase 2.2)

**Inputs:** `pages/*.json` (wikitext) + `cargo/items.json` + `cargo/recipes.json` + existing `manifest.json` with `cargo_raw_sha256`.

**Chunk types per page (in order of chunk_index):**
1. `section="stats"` — Cargo Items synthesis (all numeric stats from Cargo; use-time label from wiki-sourced thresholds ≤8/9–20/21–25/26–30/31–35/36–45/46–55/≥56).
2. `section="recipe"` — one per Cargo Recipes row matching `result == page_title`.
3. `section="stats"` — NPC template synthesis from `{{npc infobox}}` (Classic-mode damage/defense via `{{modes}}` first-positional; literal `immune`, `environment`, `ai`).
4. `section="drops"` — NPC drop DSL synthesis from numbered infobox params.
5. `section="intro"` + `section=<heading>` — prose sections via mwparserfromhell `strip_code()`, structural split at L2 headings, sliding-window fallback at 180-token target.

**Idempotency:** `INSERT … ON CONFLICT (page_id, chunk_index, game_version) DO UPDATE SET …` — re-runs update in place without duplicates.

**Code home (Phase 5.3):** the build logic is `app/rag/corpus_build.py:run_build(version, db_url, *, force=False, progress=…)`; `scripts/build_corpus.py` is a thin CLI over it. It lives in `app/` (not `scripts/`) so the re-rag worker can import it (the worker image ships `app/`, not `scripts/`, and app→scripts would invert the layering). The sync engine uses a `postgresql+psycopg://` (psycopg v3) DSN — psycopg2 is not a dependency.

**Operator re-rag as a background job (Phase 5.3, D-033 — reverses P-019):** `build_corpus.py` remains the host-side CLI fallback, but re-rag is now also operator-triggerable. `POST /admin/rerag` acquires a Redis single-job lock (→ **409** if held), records a `rerag_jobs` row, and enqueues an RQ job; the **`worker`** service runs `run_build(force=False, progress=cb)` — the idempotent upsert path, **never `--force`** (which would leave a half-deleted version on a mid-run death). The progress callback writes a Redis live hash **and** the durable `rerag_jobs` row each tick (the api's status endpoint reads both across the two-process boundary); the lock TTL is heartbeated each tick (a dead worker's lock frees). On success it writes a `corpus.reragged` audit row (§6) and marks the job succeeded; on failure it records the error and re-raises (RQ retries — safe, idempotent). Scope = **re-embed the cached corpus**; a re-scrape step (`scrape_wiki.py`) is a documented extension seam, not built (no newer 1.4.4.9 snapshot to fetch). `rerag_jobs` is operator/cross-tenant data → **no RLS**, `require_operator`-gated (D-017), like `audit_log`.

**Licensing:** wiki content is CC BY-NC-SA 4.0. `source_url` (from `canonicalurl`) is stored in every `rag_chunks` row for per-chunk attribution. Cargo data is the same CC BY-NC-SA 4.0 content served through a different API endpoint.

The trained-classifier artifact contract (SHA-pinned weights, model card, refuse-to-boot on mismatch) is **deferred to future work** along with the model itself (D-009).

## 11. RAG Architecture

_Corpus numbers measured Phase 2.2 (2026-06-05). Retrieval baseline measured Phase 2.4 (2026-06-06)._

| Concern | Choice | Status |
|---|---|---|
| Corpus | Scraped Terraria wiki (vanilla), tagged by `game_version`. Shared across tenants. **5,157 pages scraped; 22,173 chunks embedded** (4,534 pages produced ≥1 chunk; 623 empty after stripping). | D-005, measured |
| Source / ingest | `terraria.wiki.gg` via the MediaWiki API (not HTML scraping) + Cargo API (Items + Recipes); rate-limited, resumable. | D-016, Phase 2.1–2.2 |
| Embedding model | `all-MiniLM-L6-v2`, **384-dim**, local. `bge-small-en-v1.5` is a drop-in re-embed if quality demands it. | D-004, locked |
| Chunking strategy | **Hybrid structural + sliding-window + Cargo synthesis.** 180-token target, 30-token overlap, 20-token min. 29 distinct section labels (normalised; non-English headings → `"misc"`). Details: D-018. | D-018 (P-001 graduated) |
| Vector store | pgvector `rag_chunks` — `vector(384)`. **HNSW index, m=16, ef_construction=64, `vector_cosine_ops`.** | D-019 (P-002 graduated) |
| Retrieval | **Dense-only.** Phase 2.4 baseline: hit@5 = 0.667, hit@10 = 0.867, MRR@10 = 0.576, latency 5.6 ms median / 175.8 ms p95 (first-call JIT warmup). Thresholds in `eval_thresholds.yaml` (D-020). | D-008, measured |
| Hybrid (escalation) | BM25 + RRF open (P-007). Resolution criterion: hit@5 must improve ≥ 0.05 over dense-only baseline. Dense-only ships for now. | conditional (P-007 open) |
| Query transformation | **None** — HyDE rejected on latency grounds for live advice. | n/a (D-008) |
| Metadata filtering | `game_version` filter on every query (and a future `content_pack` axis for mods). | D-005, Phase 2.4 |
| Known retrieval gaps | Q11 (mage armor post-Plantera) and Q15 (post-Golem progression) are persistent dense-only failures: the query does not name its answer entity. See EVALS.md §1.6. | Phase 2.4 finding |

## 12. Tracing and Logging

_Status: implemented (Phase 1.6). All three subsections below are live._

### 12.1 Tracing

Langfuse, self-hosted in the compose stack (D-013). At `api` startup, `app/infra/tracing.py::init_langfuse(secrets.langfuse)` initializes the SDK and calls `auth_check()`; failure → refuse to boot. A single trace is started per HTTP request by `RequestContextMiddleware`. Every router decision, agent tool call, LLM call, and RAG retrieval becomes a child span; attributes include model name, token counts, latency, and tool I/O **after redaction**.

### 12.2 Logging

Structured JSON via `app/core/logging.py::JSONFormatter`:

```json
{
  "timestamp": "ISO-8601 (UTC)",
  "level": "info | warning | error | critical | debug",
  "service": "api",
  "event": "logger name (e.g. app.infra.vault)",
  "message": "human-readable message",
  "request_id": "uuid v4 — empty outside request scope",
  "trace_id": "langfuse trace id — empty outside request scope",
  "tenant_id": "set within an authenticated request, redacted-safe"
}
```

`request_id` / `trace_id` / `tenant_id` flow via `contextvars` set by `RequestContextMiddleware`. Healthcheck access-log noise is suppressed by a `HealthzFilter`.

### 12.3 Redaction

`app/infra/redaction.py` runs before any log line, trace span, or stored payload leaves the service boundary. It strips secrets (tokens, keys) and is the proof point for the "logs are redacted" graded line. Patterns defended in SECURITY.md.

## 13. Surfaces

### 13.1 Streamlit Admin (`frontend-admin/`)

Operator / test bench on `localhost:8501` (Streamlit). **Implemented Phase 5.2.** Operator-gated — a player token logs in but is blocked from the bench (the real gate is the backend `require_operator` → 403; the UI just hides it). All API calls are **server-side** (httpx from the Streamlit process) → **no CORS** (not a browser origin). Tabs:
- **Test chat (centerpiece, the demo fallback — RUNBOOK §7.1):** pick a **preset** `StatePayload` (melee pre-boss / ranger post-EoC / mage hardmode — real `item_id`s where confident, D-026) + a question → `POST /bot/ask` → renders the **answer**, **routing** (faq/agent), session_id, and the raw payload sent. The full router → agent/RAG path, no Terraria.
- **Versions** — stored corpus versions via `GET /versions`, **plus a re-rag control (Phase 5.3, D-033):** pick a version + **Re-rag** → `POST /admin/rerag` → a polling progress bar (stage + done/total, refreshed every 2s via a fragment) driven by `GET /admin/rerag/status/{id}` → succeeded/failed terminal state; a 2nd click while one runs surfaces the **409** ("already running"). The `build_corpus.py` CLI stays the fallback.
- **Tenants** + **Audit log** — the operator views `GET /admin/tenants` + `GET /admin/audit-log` (cross-tenant, `require_operator`-gated; not RLS-scoped — D-017).

`/admin/versions/check` (P-018) and the `/admin/rerag` button (P-019) are deferred — the `build_corpus.py` script is the must-have (ARCH §10).

### 13.2 React Config Portal (`frontend-user/`)

Player-facing **configuration** surface — Vite + React + TypeScript, a **polished** demo surface (D-011 revision). **No chat. Implemented Phase 5.1.** Screens:
- **Login / Register / Continue as guest** — JWT pair stored client-side (localStorage, **token-only — no password**); Bearer on authed calls; `401 → POST /auth/refresh + retry`, else re-login (guests are access-only, no refresh).
- **Version** — dropdown from `GET /versions` (public, shared corpus metadata).
- **Preferences** — `GET`/`PATCH /me/preferences` (selected version); persists across reload. _(stored `selected_version` not yet consumed by `/bot/ask` retrieval — P-017.)_
- **Account** — right-to-erasure button (`DELETE /me`) behind a confirm step (D-032).

Auth: Bearer JWT from `/auth/jwt/login` or `/auth/guest`, stored client-side. Served as a static bundle (nginx) on `:5173` (compose `frontend-user`); the API base is baked at build time (`VITE_API_BASE_URL`, default `http://localhost:8000`) and CORS for this origin is configured backend-side (locked allow-list, never `*`). The design-token SKILL was unavailable in the build env → standard React/CSS defaults.

**Two clients, two logins (design choice):** the portal and the game-client mod are **separate clients with separate logins** — the portal's JWT lives in the **browser** (`localStorage`), the mod's in **`token.json`** (D-027). Logging into one does **not** log into the other; a player authenticates **once per client**. **Guest is portal-only** — the mod's `/bot login` is real-account only (no guest path). Erasure (`DELETE /me`) is hidden for guest sessions (a guest has no persisted data to delete).

### 13.3 Game Client (`client/`) — production chat surface

A singleplayer C# tModLoader mod (.NET 8, tModLoader v2026.4.3.0 / Terraria 1.4.4.9 — D-016). **This is the surface players actually chat through.**

**Structure (`client/TerraMind/`, fresh build — the Phase 1.2 spike was throwaway):**
- `TerraMind.cs` (Mod class), `build.txt`, `TerraMind.csproj` (imports `..\tModLoader.targets`; `<Nullable>enable</Nullable>`).
- `Commands/BotCommand.cs` — the `/bot` `ModCommand`.
- `State/StateDtos.cs` — `StatePayloadDto` etc. with explicit `[JsonPropertyName]` (snake_case) matching the backend Pydantic schema exactly.
- `State/StateReader.cs` — reads `Main.LocalPlayer` → DTO; `State/BossFlags.cs` — `NPC.downed*` → canonical boss names.
- Builds inside `<tModLoader>/ModSources/TerraMind/` (RUNBOOK §10).

- **Invocation:** a `/bot` command via tModLoader's `ModCommand` (`CommandType.Chat`; not `@bot` chat interception — no clean first-party hook).
- **State read (implemented Phase 4.2):** `Main.LocalPlayer` — `armor[0..2]`→`gear.armor`, `armor[3..9]`→`gear.accessories`, `HeldItem`→`gear.weapon`, `inventory[0..49]`→`inventory`, `statLife`/`statLifeMax2`/`statMana`/`statManaMax2`/`statDefense`→`stats` — plus world flags (`Main.hardMode`, `NPC.downed*`, `WorldGen.crimson` for the EoW/BoC split, `Player.Zone*`→biome). Serializes `item.type` as the canonical `ItemRef.item_id` (== Cargo `itemid`, drives class detection via D-026); `item.Name`/`Lang.prefix[..]` are sent for readability (localization-dependent, not canonical). Boss-name strings are chosen to normalize to the tokens the backend's `_normalize`/`suggest_next_boss` check.
- **Transport (Phase 4.3):** async `HttpClient` — never blocks the game thread; prints `"thinking…"` via `Main.NewText`, then renders the reply. The `QueueMainThreadAction` marshal helper is in place from 4.2 (a post-`await` `Main.*` call must be marshaled — the spike's critical finding).
- **Auth (Phase 4.3 — shipped, all 3 commits):** holds no password and no API key. Login is a **`/bot login <user> <pass>` chat command** → `POST /auth/jwt/login` (form-encoded; password in-memory for that one call, then discarded); the **config holds the backend URL only** (D-028), never credentials. The token pair is persisted to `token.json` (tokens only), restored on launch with a world-entry confirmation, and the **refresh** token is exchanged at `POST /auth/refresh` **on launch and on a 401** for a short-lived access JWT (D-027; `/client/token` folded in). `/bot logout` deletes `token.json` + denylists the refresh token server-side (D-029). **Verified in-game across all 3 commits** (login round-trip / persistence+restore / refresh+logout) — evidence in `client/VERIFICATION.md` (the no-CI gate); rebuild 0 errors/0 warnings.
- **No CI:** building a tModLoader mod in CI needs the tModLoader runtime/targets and is fragile for little value — a deliberate skip. **Verification is manual, in-game** (RUNBOOK §10): `/bot test` logs the `StatePayload` JSON to `client.log`, eyeballed against the real character. Phase 4.2 verified across 7 runs.
- **Spike first:** Day-1 throwaway proved the read-state → HTTP → render round-trip before any feature work.