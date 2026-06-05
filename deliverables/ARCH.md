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
| `db` | Postgres 16 with `pgvector`. Tenant data + the shared, version-tagged wiki corpus. |
| `redis` | Redis 7 for short-term session memory (TTL) and service-layer caches. |
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

_Status: design (target flow; phases fill it in)._

1. In game, the player types `/bot <question>`. The mod (`client/`) collects a **state payload**: equipped armor set + held weapon + accessories, inventory summary, `Main.hardMode`, the `NPC.downed*` boss flags, current biome, and the tenant's selected `game_version`.
2. The mod presents its identity (see §6 / P-005) to `POST /client/token` and receives a short-lived JWT. It POSTs `{message, state}` to `POST /bot/ask` with the Bearer token.
3. `app/api/bot.py` authenticates, and `services` sets the **RLS tenant context** on the session from the JWT's `tenant_id`.
4. **Guardrails input check** (`app/guardrails/`): block prompt-injection / progression jailbreaks ("give me dev items") before any LLM call.
5. **Classifier router** (`app/services/router.py`): an easy FAQ ("Copper Shortsword recipe?") goes to a deterministic RAG flow; a hard, state-dependent query ("why do I keep dying to Skeletron?") goes to the agent.
6. **Bounded agent** (`app/agent/`, LangGraph): runs up to **MAX_ROUNDS** iterations (value → P-008) over tools `query_wiki` (RAG, version-filtered), `analyze_loadout` (reads the state payload), `suggest_next_boss`.
7. **RAG retrieval** (`app/rag/`): dense query against the shared corpus, filtered to the tenant's selected `game_version` (D-005, D-008).
8. **Short-term memory** (`app/memory/`): the current session's recent turns are loaded from Redis and the new turn appended, under TTL (§8, P-004).
9. **Guardrails output check**: scan the drafted reply before it leaves the boundary.
10. The whole turn runs under one Langfuse span opened in step 3 (§12.1).
11. `POST /bot/ask` returns a **single JSON reply** (the game chat renders one message via `Main.NewText` — SSE streaming into a game chat line is unnecessary here; the Streamlit test chat in §13.1 may stream for development convenience).

## 6. Authentication, Authorization & Tenancy

_Status: partial (Phase 1.6). Vault secret loading, DB session factory, ORM models, structured JSON logging, Langfuse tracing, and redaction wired. JWT/fastapi-users auth wires in Phase 4.1._

**Library:** `fastapi-users[sqlalchemy]` with `BearerTransport` + `JWTStrategy`.

**JWT signing key:** resolved from Vault at lifespan startup (`secrets.jwt.signing_key`, `HS256`). Read from `request.app.state` at request time — never from a module import or env var.

**Tenant model:** a tenant is a **player account** (or a guest). Every player-data row carries `tenant_id`; the JWT carries it; the service layer sets it as the RLS context. The wiki corpus is **not** tenant-scoped (D-005).

**Registration:** players **self-register** through the React portal (D-011). **No email verification, no password reset** (cut — see brief; zero grading value, live-demo failure risk). **Guest mode** = an ephemeral tenant with a TTL and no persistence; erasure is a no-op for guests.

**Game-client identity (OPEN — P-005):** in singleplayer there is no multiplayer server ID, so what the mod presents to `POST /client/token` is undecided. Candidates: a portal-issued account token pasted/configured into the mod, a locally generated per-install UUID bound to an account, or a Steam ID. Each has different isolation properties; resolved in the auth + client phase and promoted from P-005 to a `D-NNN`.

**Role model:** `is_superuser: bool` on `tenants`:

| Role | `is_superuser` | Permissions |
|---|---|---|
| `player` | `False` | Play via the mod, configure own profile, select version, set prefs, erase own data. |
| `operator` | `True` | All player perms + manage corpora, trigger re-rag, view tenants, use the admin test chat. |

First operator is bootstrapped via a script (RUNBOOK §3).

## 7. Endpoint Inventory

_Status: design. Phase tags added as endpoints land._

| Method | Endpoint | Roles | Notes |
|---|---|---|---|
| `POST` | `/auth/jwt/login` | Public | fastapi-users login; returns `access_token`. |
| `POST` | `/auth/register` | Public | Player self-registration (no email verification). |
| `POST` | `/auth/guest` | Public | Create an ephemeral guest tenant. |
| `POST` | `/client/token` | Player | Exchange game-client identity (P-005) for a short-lived JWT. |
| `GET` | `/healthz` | Public | Liveness probe. |
| `POST` | `/bot/ask` | Player | Send `{message, state}`; returns a single JSON advice reply. |
| `GET` | `/versions` | Player | List available wiki corpus versions. |
| `GET` | `/me/preferences` | Player | Read own preferences (incl. selected version). |
| `PATCH` | `/me/preferences` | Player | Update preferences. |
| `DELETE` | `/me` | Player | Right to erasure — purge own Postgres rows + Redis session (audit-logged). |
| `GET` | `/admin/versions/check` | operator | Check whether the live wiki has a newer version than the latest stored snapshot. |
| `POST` | `/admin/rerag` | operator | Trigger a re-rag (snapshot + embed) as a background job (button is stretch; script is must-have). |
| `GET` | `/admin/tenants` | operator | List tenants. |
| `GET` | `/admin/audit-log` | operator | Audit log (erasure + re-rag events). |

## 8. Memory Plan

### 8.1 Short-Term (Redis) — the only memory tier

Per-session message history as a Redis list under `session:{tenant_id}:{session_id}:messages`; each element a JSON `{"role", "content"}`.

- **TTL:** value → **P-004** (defended during the memory phase).
- **Sliding window:** recent-N turns via `RPUSH` + `LTRIM`; N → P-004.
- **Module:** `app/memory/short_term.py` — `append_message`, `get_history`, `clear`.
- **Injection:** the Redis client is passed as a parameter; no global import.

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

**Licensing:** wiki content is CC BY-NC-SA 4.0. `source_url` (from `canonicalurl`) is stored in every `rag_chunks` row for per-chunk attribution. Cargo data is the same CC BY-NC-SA 4.0 content served through a different API endpoint.

The trained-classifier artifact contract (SHA-pinned weights, model card, refuse-to-boot on mismatch) is **deferred to future work** along with the model itself (D-009).

## 11. RAG Architecture

_Corpus numbers filled from the Phase 2.2 build run (2026-06-05). Retrieval numbers (hit@k, latency) remain PENDING until Phase 2.4 measures them against the 15-question golden set._

| Concern | Choice | Status |
|---|---|---|
| Corpus | Scraped Terraria wiki (vanilla), tagged by `game_version`. Shared across tenants. **5,157 pages scraped; 22,173 chunks embedded** (4,534 pages produced ≥1 chunk; 623 empty after stripping). | D-005, measured |
| Source / ingest | `terraria.wiki.gg` via the MediaWiki API (not HTML scraping) + Cargo API (Items + Recipes); rate-limited, resumable. | D-016, Phase 2.1–2.2 |
| Embedding model | `all-MiniLM-L6-v2`, **384-dim**, local. `bge-small-en-v1.5` is a drop-in re-embed if quality demands it. | D-004, locked |
| Chunking strategy | **Hybrid structural + sliding-window + Cargo synthesis.** 180-token target, 30-token overlap, 20-token min. 29 distinct section labels (normalised; non-English headings → `"misc"`). Details: D-018. | D-018 (P-001 graduated) |
| Vector store | pgvector `rag_chunks` — `vector(384)`. **HNSW index, m=16, ef_construction=64, `vector_cosine_ops`.** | D-019 (P-002 graduated) |
| Retrieval | **Dense-only first.** Baseline hit@k PENDING (Phase 2.4). | D-008, RAG phase |
| Hybrid (escalation) | BM25 + RRF added **only if** dense underperforms, recorded as a number-backed delta. | conditional (P-007) |
| Query transformation | **None** — HyDE rejected on latency grounds for live advice. | n/a (D-008) |
| Metadata filtering | `game_version` filter on every query (and a future `content_pack` axis for mods). | D-005, RAG phase |

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

Operator / test bench on `localhost:8501`. Pages:
- **Login** — operator JWT login.
- **Corpus & Versions** — list stored versions, run "check for new version", trigger re-rag, view manifest + counts.
- **Tenants** — read-only tenant list, audit-log view.
- **Test Chat** — exercises the `/bot/ask` flow with a hand-entered or mocked state payload, so the full agent path is demoable without launching Terraria. May stream for dev convenience.

### 13.2 React Config Portal (`frontend-user/`)

Player-facing **configuration** surface, built with Vite. **No chat.** Kept minimal (forms) so it can degrade to a Streamlit page if the clock tightens (D-011). Screens:
- **Login / Register / Continue as guest.**
- **Version** — dropdown of available corpora + "check for new version".
- **Preferences** — selected version + any per-tenant settings.
- **Account** — right-to-erasure button (`DELETE /me`).

Auth: Bearer JWT from `/auth/jwt/login` or `/auth/guest`, stored client-side.

### 13.3 Game Client (`client/`) — production chat surface

A singleplayer C# tModLoader mod. **This is the surface players actually chat through.**

- **Invocation:** a `/bot` command via tModLoader's `ModCommand` (not `@bot` chat interception — no clean first-party hook).
- **State read:** `Main.LocalPlayer` (equipped armor / accessories / held item / inventory / HP-MP) + world flags (`Main.hardMode`, `NPC.downed*`). Signatures verified against the ExampleMod repo for the targeted tModLoader version (D-016).
- **Transport:** async `HttpClient` — never blocks the game thread; prints `"thinking…"` via `Main.NewText`, then renders the reply.
- **Auth:** holds no API keys; exchanges identity (P-005) for a short-lived JWT at `POST /client/token`.
- **No CI:** building a tModLoader mod in CI needs the tModLoader runtime/targets and is fragile for little value — a deliberate skip (documented in EVALS/RUNBOOK).
- **Spike first:** Day-1 throwaway proves the read-state → HTTP → render round-trip before any feature work.