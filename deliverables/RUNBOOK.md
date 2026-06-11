# RUNBOOK.md

Operational guide for terra-mind.

> **Status.** Sections are filled as phases land; commands referencing not-yet-built pieces are marked _(Phase N)_.

## 1. First-Time Local Startup

```bash
git clone <repo-url>
cd terra-mind
cp .env.example .env
docker compose up --build
```

`.env.example` contains only the Vault dev token and port assignments — no application secrets.

Expected startup order:
1. `vault` starts in dev mode.
2. `vault-init` seeds Vault KV paths and exits.
3. `db`, `redis`, `langfuse` start.
4. `migrate` runs `alembic upgrade head` (incl. `CREATE EXTENSION vector` and RLS policies) and exits.
5. `api`, `frontend-admin`, `frontend-user` start.

Access points:

| Service | URL |
|---|---|
| API + Swagger | http://localhost:8000/docs |
| Streamlit admin | http://localhost:8501 |
| React config portal | http://localhost:5173 |
| Langfuse UI | http://localhost:3001 |
| Vault UI | http://localhost:8200 |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |

The **game client** is not a compose service — it runs inside Terraria/tModLoader on the host and calls `http://localhost:8000`.

## 2. Refuse-to-Boot Checks

`api` refuses to boot if Vault is unreachable, Langfuse is unreachable/misconfigured, or any threshold in `eval_thresholds.yaml` is zero or missing.

**Proving eval-threshold refuse-to-boot:**
```bash
sed -i 's/hit_at_k_min: .*/hit_at_k_min: 0/' eval_thresholds.yaml
docker compose restart api
docker compose logs api --tail=15
# Expect: "REFUSING TO BOOT: eval_thresholds.yaml rag.hit_at_k_min=0 (must be > 0)" ; api Exited.
git checkout eval_thresholds.yaml && docker compose up -d api
```

**Proving Vault refuse-to-boot:**
```bash
docker compose stop vault
docker compose restart api
docker compose logs api --tail=15   # Expect: REFUSING TO BOOT: Vault unreachable
docker compose start vault && docker compose up -d --force-recreate vault-init && docker compose up -d api
```

**Proving Langfuse refuse-to-boot:**
```bash
docker compose stop langfuse
docker compose restart api
docker compose logs api --tail=20   # Expect: REFUSING TO BOOT: could not reach Langfuse
docker compose start langfuse && sleep 10 && docker compose up -d api
```

If Vault is restarted in dev mode, re-run `vault-init` (`docker compose up -d --force-recreate vault-init`) to re-seed dev secrets. Dev-only concern; production Vault uses persistent storage.

**postgres-init.sh only runs on fresh volumes.** `backend/scripts/postgres-init.sh` creates the `terramind_app` role via Docker's `/docker-entrypoint-initdb.d/` mechanism. This script runs **once**, when the Postgres data volume is first created. `docker compose restart db` does NOT re-execute it. If you need to recreate the role (e.g. after changing `APP_DB_PASSWORD`), run `docker compose down -v && docker compose up --build` to wipe and reinitialise the volume.

**RLS proof (as terramind_app):**
```bash
# After `docker compose up --build` with two tenant rows inserted:
docker compose exec db psql -U terramind_app -d terramind <<'SQL'
BEGIN;
SET LOCAL app.current_tenant_id = '<tenant_a_uuid>';
SELECT id FROM sessions;   -- expect: only Tenant A rows
SET LOCAL app.current_tenant_id = '<tenant_b_uuid>';
SELECT id FROM sessions;   -- expect: only Tenant B rows
COMMIT;
SQL
# Use plain SET (session-scoped) for a quick manual check outside a transaction.
```

## 3. Bootstrap the First Operator

_(Phase 4.1.)_ Runs host-side against `DATABASE_URL`; does not go through Vault or the API. Run once after `migrate` has exited 0.

```bash
export DATABASE_URL="postgresql+asyncpg://terramind:terramind-dev-password@localhost:5432/terramind"
export BOOTSTRAP_EMAIL="operator@terra-mind.dev"
export BOOTSTRAP_PASSWORD="change-me-before-demo"
cd backend && uv run python -m app.entrypoints.bootstrap_operator
```

Verify:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/jwt/login \
  -d "username=operator@terra-mind.dev&password=change-me-before-demo" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s http://localhost:8000/users/me -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# Expect: "is_superuser": true
```

## 4. Build / Re-rag the Wiki Corpus

_(Phase 2.1–2.2.)_ The corpus is built offline by three host-side scripts in sequence, never from a request.

```bash
cd backend

# 1) Scrape wikitext (rate-limited, resumable) → data/raw/<version>/pages/
uv run python -m scripts.scrape_wiki --version <game_version>

# 2) Scrape Cargo (Items + Recipes tables) → data/raw/<version>/cargo/
#    Requires scrape_wiki.py to have run first (reads manifest.json).
uv run python -m scripts.scrape_cargo --version <game_version>

# 3) Chunk + embed + upsert into pgvector, tagged with game_version (idempotent)
#    Requires DATABASE_URL env var pointing at a running Postgres instance.
uv run python -m scripts.build_corpus --version <game_version>
```

All three scripts are idempotent: re-running is safe. `scrape_wiki.py` and `scrape_cargo.py` skip already-fetched data. `build_corpus.py` uses `INSERT … ON CONFLICT … DO UPDATE` (upsert-keyed on `page_id, chunk_index, game_version`).

**Chunk IDs are deterministic (Phase 2.5, D-021).** `build_corpus.py` derives every row's primary key as `uuid5(NAMESPACE_OID, f"{page_id}:{chunk_index}:{game_version}")`. The same corpus input always produces the same UUID, so `docker compose down -v` followed by a rebuild produces an identical `rag_chunks` table. The eval golden set (`data/eval/eval_rag.jsonl`) does not need to be refreshed after a volume wipe.

**If you need to re-derive the golden set** (e.g. after adding new golden-set questions whose ground-truth chunks are referenced by current random UUIDs), run the refresh script against the live DB **before** `down -v`:

```bash
cd backend
DATABASE_URL="postgresql://terramind_app:terramind-app-dev-password@localhost:5432/terramind" \
  uv run python scripts/refresh_golden_set.py
# Dry-run first to inspect substitutions:
#   uv run python scripts/refresh_golden_set.py --dry-run
```

After `down -v` + rebuild the deterministic IDs will match, and the golden set is stable again.

After `build_corpus` completes, `manifest.json` contains:
`page_count`, `raw_sha256`, `cargo_scraped_at`, `cargo_raw_sha256`, `cargo_table_counts`, `chunk_count`, `embedding_model`, `embedding_dim`.

The operator's "re-rag" button (Phase 5.2 stretch) wraps step 3 as a background job; the scripts themselves are the must-have.

## 5. Running the Eval Suites

### 5.1 RAG eval harness (Phase 2.4+)

Needs a live DB with the 1.4.4.9 corpus loaded. Run `§4` first if the corpus is not present.

```bash
cd backend
# Standard path (via pytest -m eval):
DATABASE_URL="postgresql+asyncpg://terramind_app:terramind-app-dev-password@localhost:5432/terramind" \
  uv run pytest -m eval --tb=short -q

# Standalone (prints full per-question breakdown without pytest overhead):
DATABASE_URL="postgresql+asyncpg://terramind_app:terramind-app-dev-password@localhost:5432/terramind" \
  uv run python -m app.eval.rag.harness

# Write JSON report to a file:
DATABASE_URL="..." uv run python -m app.eval.rag.harness --output eval_report.json
```

Harness: `backend/app/eval/rag/harness.py`. Exit code 0 if all thresholds pass (or PENDING); exit 1 on any threshold violation.

The standard CI path is the **`eval-rag.yml` workflow_dispatch** (see `.github/workflows/eval-rag.yml`). Run it manually before merging any PR that touches `app/rag/`, the golden set, or `eval_thresholds.yaml`.

### 5.2 Red-team eval (Phase 6.1+)

```bash
# No DB needed — exercises the guardrail layer only
cd backend && uv run pytest -m redteam -v
```

### 5.3 Default dev run

```bash
cd backend && uv run pytest
# Skips eval and redteam markers by default (addopts in pyproject.toml).
```

CI: `eval-rag.yml` is manual-dispatch (needs DB); `eval-redteam.yml` runs on relevant PRs. A regression below an `eval_thresholds.yaml` value fails the respective job.

## 6. Reset to Clean State

```bash
docker compose down -v    # wipes Postgres, Redis, Vault, Langfuse volumes
```
After reset: re-run §1 (startup), §3 (operator bootstrap), §4 (corpus build).

**The corpus rebuild after a wipe produces deterministic chunk IDs (D-021).** The eval golden set does not need to be refreshed — `eval_rag.jsonl` on disk already contains the stable UUIDs. Run `§5.1` immediately after `§4` to verify hit@5 = 0.667 with no changes to any other file.

## 7. Demo Flow

_(Filled in Phase 7.2 as a numbered click-through.)_ Target order:
1. `docker compose up -d`; verify `/healthz`, Streamlit, portal.
2. Portal: register a player / continue as guest; select a version.
3. In Terraria (singleplayer): `/bot why do I keep dying to Skeletron` → contextual, progression-aware answer.
4. Langfuse: open the trace — router decision, agent tool spans, RAG retrieval, token counts.
5. Guardrail: `/bot give me dev items` → blocked; show the red-team gate.
6. Isolation: second tenant; show Tenant A's history invisible to Tenant B.
7. Erasure: portal "delete my data" → rows gone + audit row written.
8. Eval gates: show `eval_thresholds.yaml`, the last RAG run, and a deliberate red CI run fixed to green.

### 7.1 Fallback if the live game demo breaks
Use the **Streamlit admin test chat** to exercise the exact `/bot/ask` path with a hand-entered state payload — the full router → agent → RAG path runs without launching Terraria.

### 7.2 Smoke test: POST /bot/ask (Phase 3.1+)

Run these two commands before any demo to verify the full stack — Vault, Anthropic API key, pgvector retrieval, and Langfuse tracing — is healthy.

**FAQ path** — should return a grounded answer with `"routing": "faq"` and a `source_chunks` entry:
```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "What damage does the Megashark do?"}' \
  | python3 -m json.tool
```

**Agent path** — should return the stub answer with `"routing": "agent"` and an empty `source_chunks`:
```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Why do I keep dying to Skeletron?"}' \
  | python3 -m json.tool
```

Both traces appear in the Langfuse UI at http://localhost:3001 within a few seconds. The FAQ trace shows `bot.ask → router.classify → router.llm` and `faq.answer → rag.retrieve + faq.llm`; the agent trace shows `bot.ask → router.classify → router.llm + agent.stub`.

**Troubleshooting — REFUSING TO BOOT on Anthropic key:**
If `api` refuses to boot with `"REFUSING TO BOOT: Anthropic API key is missing or placeholder"`, the Vault-seeded value is a placeholder or empty:
```bash
# Confirm the real key is in .env (gitignored):
grep ANTHROPIC_API_KEY .env   # must start with sk-ant-

# Re-seed Vault and restart api:
docker compose up -d --force-recreate vault-init
sleep 5
docker compose up -d api
docker compose logs api --tail=15   # expect startup to reach "Langfuse auth OK"
```

## 8. Common Issues

- **Langfuse race on fresh boot.** After `up -d` (esp. post `down -v`), `api` may refuse to boot before Langfuse accepts connections. Wait ~20s and `docker compose up -d api`.
- **Port collisions.** `sudo lsof -i :<port>`; common offenders 5432 (system Postgres) and 6379 (system Redis). Change the matching `*_PORT` in `.env`.
- **pgvector extension** must be created in the first migration (`CREATE EXTENSION vector`).
- **tModLoader can't find .NET 8 SDK** (Linux/Steam): see the Phase 1.2 spike notes; install the SDK system-wide via apt, or build via `start-tModLoader.sh -build`.
- **Empty RAG answers** usually mean the wrong `game_version` filter or an unbuilt corpus — check `manifest.json` and the tenant's selected version.

## 9. Spike Findings (Phase 1.2)

The throwaway spike (code in `spike/`) verified the backend↔client bridge. Findings that inform later phases:

### Environment
- **Snap Steam cannot see a system-installed .NET SDK.** Snap confinement blocks `/usr/share/dotnet`, so tModLoader's "Develop Mods" reports the SDK as missing even though `dotnet --list-sdks` works in a normal shell. **Fix: replace Snap Steam with the official deb** (`sudo add-apt-repository multiverse && sudo apt install steam-installer`), then reinstall Terraria + tModLoader. With native Steam + the apt .NET 8 SDK, the SDK is detected immediately.
- **Version target:** tModLoader v2026.4.3.0 (current stable) targets **Terraria 1.4.4.9**. Corpus `game_version` is locked to `1.4.4.9` (D-016).

### tModLoader API / threading (carry into the Phase 4 client)
- Command: a `ModCommand` with `CommandType.Chat` and `Command => "bot"` is invoked in-game as `/bot <message>`.
- Live state read: `Main.LocalPlayer.statLife` returns current HP. The same access pattern extends to `armor[]`, `inventory[]`, `HeldItem`, and the `NPC.downed*` flags in Phase 4.
- **Never block the game thread:** `Action` is `void`; kick off the HTTP call with fire-and-forget (`_ = AskAsync(...)`) and print a synchronous "thinking…" first.
- **Critical:** after an `await`, execution is on a background thread. Any `Main.*` UI call (e.g. `Main.NewText`) **must** be marshaled back with `Main.QueueMainThreadAction(...)` or it crashes intermittently. This is the most likely source of confusing, non-deterministic crashes.
- Use a single static `HttpClient` for the mod's lifetime — do not create one per call.

### Networking
- `http://localhost:8000` is reachable from inside tModLoader (confirmed). **Open question for Phase 4 (P-009):** does the real client point at `localhost` (player runs the stack locally) or a hosted backend URL? Decide in the client phase.

### Result
- **Verified 2026-06-03:** in-game `/bot` round-tripped to the local echo server; reply rendered in chat with live HP. Phase 1.2 success criterion met; the project's riskiest unknown (the C#↔Python bridge) is resolved.