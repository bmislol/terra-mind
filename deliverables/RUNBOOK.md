# RUNBOOK.md

Operational guide for terra-mind.

> **Status.** Sections are filled as phases land; commands referencing not-yet-built pieces are marked _(Phase N)_.

## 1. First-Time Local Startup

```bash
git clone <repo-url>
cd terra-mind
cp .env.example .env

# 1) Produce the Cargo data the api needs to BOOT (host-side, network-only — no DB).
#    A clean clone has no data/raw (gitignored). The api mounts backend/data/raw
#    read-only and REFUSES TO BOOT without data/raw/<version>/cargo/items.json
#    (class detection, D-026). These are §4 steps 1–2:
cd backend
uv run python -m scripts.scrape_wiki  --version 1.4.4.9
uv run python -m scripts.scrape_cargo --version 1.4.4.9
cd ..

# 2) Boot the stack (api now finds items.json via the ./backend/data/raw:ro mount):
docker compose up --build -d

# 3) Populate pgvector for RAG answers (DB is up now — §4 step 3; see §4 for the DSN):
#    cd backend && DATABASE_URL=... uv run python -m scripts.build_corpus --version 1.4.4.9
```

`.env.example` contains only the Vault dev token and port assignments — no application secrets. Steps 1 and 3 are the same host-side corpus scripts documented in **§4**; step 1 is split out because `items.json` is a **boot-time** dependency of the api (not just a `build_corpus` input).

Expected startup order:
1. `vault` starts in dev mode.
2. `vault-init` seeds Vault KV paths and exits.
3. `db`, `redis`, `langfuse` start.
4. `migrate` runs `alembic upgrade head` (incl. `CREATE EXTENSION vector` and RLS policies) and exits.
5. `api` starts — loads the embedding model + the Cargo class-detection index (logs `item_classifier ready: 445 cargo weapons …`) — then `frontend-admin`, `frontend-user`.

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

_(Phase 4.1a.)_ Runs host-side against `DATABASE_URL`; does not go through Vault or the API. Run once after `migrate` has exited 0.

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

> **`scrape_cargo`'s `items.json` is also a *runtime* dependency of the api** (not just a `build_corpus` input). The api mounts `backend/data/raw` read-only and refuses to boot without `data/raw/<version>/cargo/items.json` for class detection (D-026). So step 2 must run **before** the api starts — see §1.

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
3. In Terraria (singleplayer): `/bot why do I keep dying to Skeletron` → contextual, progression-aware answer. _(Detailed game-surface click-through — FAQ + agent paths, gear-swap, trace — is in §10 "In-game end-to-end demo".)_
4. Langfuse: open the trace — router decision, agent tool spans, RAG retrieval, token counts.
5. Guardrail: `/bot give me dev items` → blocked; show the red-team gate.
6. Isolation: second tenant; show Tenant A's history invisible to Tenant B.
7. Erasure: portal "delete my data" → rows gone + audit row written.
8. Eval gates: show `eval_thresholds.yaml`, the last RAG run, and a deliberate red CI run fixed to green.

### 7.1 Fallback if the live game demo breaks
Use the **Streamlit admin test chat** to exercise the exact `/bot/ask` path with a hand-entered state payload — the full router → agent → RAG path runs without launching Terraria.

### 7.2 Smoke test: POST /bot/ask (Phase 3.1+; auth-gated since 4.1a)

Run these before any demo to verify the full stack — Vault, Anthropic key, pgvector retrieval, Langfuse tracing, **and the auth gate** — is healthy.

**Get an access token first.** Since Phase 4.1a, `/bot/ask` requires a Bearer **access** token (an unauthenticated call returns 401) — register a player (or reuse one), log in, and capture the access token:
```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "smoke@example.com", "password": "smoke-pw-123"}' >/dev/null
TOKEN=$(curl -s -X POST http://localhost:8000/auth/jwt/login \
  -d 'username=smoke@example.com&password=smoke-pw-123' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
# Or, for a throwaway identity: TOKEN=$(curl -s -X POST .../auth/guest | jq -r .access_token)
```

**FAQ path** — should return a grounded answer with `"routing": "faq"` and a `source_chunks` entry:
```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "What damage does the Megashark do?"}' \
  | python3 -m json.tool
```

**Agent path (stateless)** — should return a real progression-aware answer with `"routing": "agent"`. With no state payload, `analyze_loadout` returns `needs_llm_fallback=true` (no fabricated class) and `suggest_next_boss` treats the world as pre-boss:
```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Why do I keep dying to Skeletron?"}' \
  | python3 -m json.tool
```

**Auth gate check** — an unauthenticated call must be rejected:
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" -d '{"message": "hi"}'   # expect 401
```

Both traces appear in the Langfuse UI at http://localhost:3001 within a few seconds. The FAQ trace shows `bot.ask → router.classify → router.llm` and `faq.answer → rag.retrieve + faq.llm`; the agent trace shows `bot.ask → router.classify → router.llm + agent.run` (with each `chat_with_tools` generation and `rag.retrieve` span as flat siblings under `agent.run` — see P-013). **Note (P-009):** Langfuse 2.60.10 renders token counts as 0/0 in the UI; the SDK sends correct counts. Use the Anthropic console for token/cost totals (D-025).

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

### 7.3 Agent path smoke test (with state)

The canonical agent-path check sends a hard, state-dependent question with a full state payload — a Ranger in early pre-Hardmode (Fossil armor + a gun, Eye of Cthulhu and Eater of Worlds downed, Skeletron not yet beaten). This exercises the real LangGraph agent (D-024): `analyze_loadout` should classify **ranger / early-pre-hardmode**, `query_wiki` should retrieve Skeletron chunks, and `suggest_next_boss` should point at Skeletron.

```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "message": "Why do I keep dying to Skeletron?",
    "state": {
      "game_version": "1.4.4.9",
      "gear": {
        "armor": [
          {"item_id": 0, "name": "fossil helmet"},
          {"item_id": 0, "name": "fossil plate"},
          {"item_id": 0, "name": "fossil greaves"}
        ],
        "accessories": [],
        "weapon": {"item_id": 0, "name": "the undertaker"}
      },
      "world": {
        "hardmode": false,
        "downed_bosses": ["Eye of Cthulhu", "Eater of Worlds"],
        "biome": "forest"
      }
    }
  }' | python3 -m json.tool
```

Expect `"routing": "agent"`, a class-aware progression-aware answer, and a non-empty `source_chunks` list (the Skeletron wiki chunks the agent retrieved). The Langfuse trace shows `bot.ask → router.classify → router.llm + agent.run`, with the per-call generation events and `rag.retrieve` spans flat under `agent.run` (P-013).

**Cold-start (LLM zero-shot fallback, D-026).** Send a question with no gear (or only starter/unknown items) so deterministic class detection finds no signal:

```bash
curl -s -X POST http://localhost:8000/bot/ask \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "message": "What class should I build toward?",
    "state": {"game_version": "1.4.4.9", "world": {"hardmode": false}}
  }' | python3 -m json.tool
```

`analyze_loadout` returns `needs_llm_fallback=true` (no fabricated class), and `execute_tools` fires one extra `claude-haiku-4-5` call (`max_tokens=8`) — visible as an **`agent.llm_classify`** span in the trace. This path adds ~$0.0002 + ~1–2 s and fires **only** when there is no clear class lean (D-026 cost addendum).

### 7.4 Reproducing Phase 3.2 measurements (D-025)

`scripts/measure_agent_cost.py` POSTs a fixed set of 10 hard questions (each with a realistic state payload) to `/bot/ask`, captures status / latency / routing / chunk counts per question, and writes a timestamped JSON file under `backend/measurements/`. Token and cost columns print `PENDING` because Langfuse 2.60.10 does not surface per-trace token counts (P-009).

```bash
# With the full stack up and a real Anthropic key seeded in Vault:
cd backend
uv run python scripts/measure_agent_cost.py            # → measurements/agent_cost_<UTC>.json
uv run python scripts/measure_agent_cost.py --url http://localhost:8000
```

**Cost methodology (run-and-read-console):** record the Anthropic credit balance / token totals on the [Anthropic console](https://platform.claude.com/usage) immediately **before** and **after** the run, then divide the token delta by the call count and apply Haiku pricing ($0.80/M input + $4.00/M output, D-023). The Phase 3.2 baseline (12 Jun 2026): 66,832 input / 4,105 output tokens for 10 calls → ~$0.07, median ~$0.005/call, p95 ~$0.020/call (Q05). See D-025 for the full table.

## 8. Common Issues

- **Langfuse race on fresh boot.** After `up -d` (esp. post `down -v`), `api` may refuse to boot before Langfuse accepts connections. Wait ~20s and `docker compose up -d api`.
- **Port collisions.** `sudo lsof -i :<port>`; common offenders 5432 (system Postgres) and 6379 (system Redis). Change the matching `*_PORT` in `.env`.
- **pgvector extension** must be created in the first migration (`CREATE EXTENSION vector`).
- **tModLoader can't find .NET 8 SDK** (Linux/Steam): see the Phase 1.2 spike notes; install the SDK system-wide via apt, or build via `start-tModLoader.sh -build`.
- **Empty RAG answers** usually mean the wrong `game_version` filter or an unbuilt corpus — check `manifest.json` and the tenant's selected version.
- **`api` refuses to boot — Cargo items file missing / truncated.** Class detection (D-026) loads `data/raw/<version>/cargo/items.json` at lifespan and refuses to boot if it is missing or has `< 100` rows. The file is **gitignored** (`data/raw/`), so it must be scraped locally **before** the api starts: `cd backend && uv run python -m scripts.scrape_cargo --version 1.4.4.9`. The path is configurable via `cargo_items_path` (default `data/raw/1.4.4.9/cargo/items.json`). **The file must also be visible *inside* the api container** — the compose api service mounts `./backend/data/raw:/app/data/raw:ro` (resolving to `/app/data/raw/<version>/cargo/items.json` under `WORKDIR /app`). If the file exists on the host but the api still refuses to boot, confirm that mount line is present. Startup logs `item_classifier ready: 445 cargo weapons (6233 cargo items)` on success; `0 cargo weapons` (or no such line) means a stale image or an unmounted/empty `data/raw`.
- **CI never boots the real lifespan.** Because the Cargo file is gitignored, CI has no `items.json`; the `min_items=100` check would refuse to boot. Unit tests therefore never start the full lifespan — they call `ItemClassifier.from_cargo_file` directly with **synthetic** fixtures, and the curated-only `DEFAULT_CLASSIFIER` covers name-based class detection in CI. A future contributor adding a full-boot test must seed a Cargo fixture or it will fail in CI (not locally).
- **Slow-connection image builds time out on torch wheels.** The embedding model (`sentence-transformers`) pulls large torch wheels (~2 GB). The Dockerfile sets `UV_HTTP_TIMEOUT=300` so `uv sync` won't abort mid-download on a slow link. Prefer a normal `docker compose build` / `up --build` — it reuses the uv cache mount (`--mount=type=cache,target=/root/.cache/uv`), so only changed layers rebuild. Avoid `--no-cache`, which forces a full ~2 GB re-download.

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
- `http://localhost:8000` is reachable from inside tModLoader (confirmed). **Resolved (D-028, was P-011):** the mod reads the backend URL from config, default `http://localhost:8000`; hosting the stack is a Section 7 stretch.

### Result
- **Verified 2026-06-03:** in-game `/bot` round-tripped to the local echo server; reply rendered in chat with live HP. Phase 1.2 success criterion met; the project's riskiest unknown (the C#↔Python bridge) is resolved.

## 10. Game Client Mod — build & verify (Phase 4.2+)

The mod source is version-controlled in `client/TerraMind/`. It has **no CI** (building a tModLoader mod needs the tModLoader runtime/targets — a deliberate skip, ARCH §13.3); "done" is the **manual** check below. Phase 4.2 reads live character state and logs the `StatePayload` JSON — **no backend call yet** (that's 4.3).

### Build
tModLoader mods build inside `<tModLoader>/ModSources/<ModName>/` (the csproj imports `..\tModLoader.targets`, which only exists there). So:

```bash
# Copy (or symlink) the source into tModLoader's ModSources. Path varies by install;
# on native-Steam Linux it's typically ~/.local/share/Terraria/tModLoader/ModSources/
cp -r client/TerraMind "<tModLoader>/ModSources/TerraMind"
#   …or symlink so edits track the repo:
# ln -s "$(pwd)/client/TerraMind" "<tModLoader>/ModSources/TerraMind"
```
Then in tModLoader: **Workshop → Develop Mods → TerraMind → Build + Reload**. (If the SDK isn't found, see §9 — use native Steam + the apt .NET 8 SDK, not Snap.) A localization-missing warning is harmless; it still builds.

### Run
1. Enable **TerraMind** in Mods, launch **Singleplayer** with any character/world.
2. Open the chat box and type **`/bot test`** (in 4.2 any `/bot <message>` dumps state; the message is captured but not sent).
3. Chat shows a one-line summary; the **full JSON is in the log**.

### Where the output is
The full `StatePayload` JSON is written via the mod logger to tModLoader's **`client.log`** (e.g. `<tModLoader>/tModLoader-Logs/client.log`, or the install's logs dir), tagged `/bot message=…  StatePayload:`. Chat lines truncate long JSON, so **the log is the source of truth**.

### What CORRECT output looks like (eyeball against your character)
```json
{
  "game_version": "1.4.4.9",
  "gear": {
    "armor": [
      {"item_id": 1281, "name": "Fossil Helmet", "prefix": null, "stack": 1},
      {"item_id": 1282, "name": "Fossil Plate", "prefix": null, "stack": 1},
      {"item_id": 1283, "name": "Fossil Greaves", "prefix": null, "stack": 1}
    ],
    "accessories": [
      {"item_id": 54, "name": "Hermes Boots", "prefix": "Quick", "stack": 1}
    ],
    "weapon": {"item_id": 98, "name": "Minishark", "prefix": "Unreal", "stack": 1}
  },
  "inventory": [
    {"item_id": 40, "name": "Wooden Arrow", "prefix": null, "stack": 250}
  ],
  "stats": {"life": 300, "max_life": 300, "mana": 60, "max_mana": 60, "defense": 14},
  "world": {"hardmode": false, "downed_bosses": ["Eye of Cthulhu", "Eater of Worlds"], "biome": "forest"}
}
```
(IDs/names illustrative.) **Done-when:** the JSON matches your real character — right `gear.armor`/`weapon`, right `downed_bosses`, correct `hardmode`, sane `stats` — and field names are exactly snake_case as above. This is the gate (no CI).

### Scrutinise these (most likely wrong, since the C# is unrun here)
- **Boss flag names** (`BossFlags.cs`) — esp. the **extended set** (`downedQueenSlime`/`downedEmpressOfLight`/`downedDeerclops`); a wrong static-field name is a **compiler error** (report the text). Confirm a **crimson** world reports "Brain of Cthulhu".
- **`max_life`/`max_mana`** — should be the character's **effective max** (`statLifeMax2`/`statManaMax2`), not 100/20.
- **Armor vs accessories** — `armor[0..2]` = the 3 armor pieces, `armor[3..9]` = accessories (not vanity/social).
- **`prefix`** — should be a name like "Unreal"/"Legendary" (via `Lang.prefix`), `null` if unmodified — not a number/garbage.
- **`biome`** — sensible for your zone, or `"forest"` default.

### Authenticated chat (Phase 4.3)

The mod is a full authenticated chat client. Nothing on disk but a **revocable token** — never a password (D-027, SECURITY §4).

1. **Backend URL (optional):** Mod Configuration → TerraMind → `BackendUrl` (default `http://localhost:8000`, D-028). The config holds the URL **only** — no credentials.
2. **Log in:** `/bot login <email> <password>` → `POST /auth/jwt/login` (**form-encoded**). The password is used for that one request and **discarded** — never written to disk, never logged. Chat shows `logged in as <email>`; the access+refresh pair is saved to `token.json` under the tModLoader save dir (`<save>/TerraMind/token.json`).
3. **Ask:** `/bot <question>` → `POST /bot/ask` with the Bearer access token + live `StatePayload` → contextual answer in chat.
4. **Stay logged in:** each launch loads `token.json` and exchanges the **refresh** token at `POST /auth/refresh` for a fresh access JWT (world-entry: `session restored — logged in`); a mid-session 401 triggers the same refresh + one retry. Survives a Terraria restart, durable past the 30-min access TTL.
5. **Log out:** `/bot logout` deletes `token.json` **and** `POST /auth/logout` (denylists the refresh `jti`, D-029) → re-login next launch; the old token is rejected.

**Verification (no CI):** all three 4.3 commits are evidenced verbatim from `client.log` in `client/VERIFICATION.md` — the in-repo gate that stands in for a green check.

### In-game end-to-end demo (Phase 4.4) — the game-surface demo script

A cold-reader click-through of the production chat surface. (The full project demo is §7; this is the game-client portion.)

1. **Stack up:** `docker compose up -d` → wait for `Application startup complete` (~100s; the log line `item_classifier ready: N cargo weapons` confirms the D-026 class detection is armed).
2. **Mod config:** Mod Configuration → TerraMind → `BackendUrl` = `http://localhost:8000` (D-028).
3. **Log in:** `/bot login <email> <password>` → `logged in as <email>` (token saved; password discarded).
4. **FAQ path (easy → deterministic RAG):** `/bot what does the Confused debuff do?` → a short factual answer; `client.log` shows `routing=faq`.
5. **Agent path (hard → bounded agent):** `/bot why do I keep dying to Skeletron?` → a progression-aware, class-grounded answer; `routing=agent` (the agent calls `analyze_loadout` + `query_wiki`).
6. **State-sensitivity:** `/bot what should I do next?` — note the class named in the answer; then **swap gear** (e.g. melee set → ranger set) and ask again → the advice changes class (Sword/Spear → bow/arrows). The answer tracks the live character, not a script.
7. **Observability:** open the Langfuse UI → the turn's trace tree: `bot.ask → router.classify → agent.run` (tool spans) or `→ faq.answer → rag.retrieve + faq.llm`, with token counts. "Every turn is one trace" (ARCH §1.1), proven for the game surface.

Evidence for the deliberate pass (both router paths, the P-016 reliability fix, the trace) is in `client/VERIFICATION.md` §4.4.