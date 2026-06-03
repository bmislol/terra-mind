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

_(Phase 2.1–2.2.)_ The corpus is built offline by scripts, never from a request.

```bash
cd backend
# 1) Scrape (rate-limited, resumable) → data/raw/<version>/
uv run python -m scripts.scrape_wiki --version <game_version>
# 2) Chunk + embed + upsert into pgvector, tagged with game_version (idempotent)
uv run python -m scripts.build_corpus --version <game_version>
```

`build_corpus` writes a `manifest.json` (`page_count`, `chunk_count`, `embedding_model`, `embedding_dim`, `raw_sha256`). Re-running is safe (upsert-keyed). The operator's "re-rag" button (stretch) wraps step 2 as a background job.

## 5. Running the Eval Suites

```bash
# RAG (needs the corpus indexed) — manual, ~$ small Anthropic cost if generation metrics on
cd backend && set -a; source ../.env; set +a
uv run pytest tests/test_eval_rag.py -m eval -v -s

# Red-team (no DB needed)
uv run pytest tests/test_eval_redteam.py -m redteam -v

# Default dev run skips both gates:
uv run pytest
```

CI: `eval-rag.yml` is manual-dispatch (needs DB); `eval-redteam.yml` runs on relevant PRs. A regression below an `eval_thresholds.yaml` value fails the job.

## 6. Reset to Clean State

```bash
docker compose down -v    # wipes Postgres, Redis, Vault, Langfuse volumes
```
After reset: re-run §1 (startup), §3 (operator bootstrap), §4 (corpus build).

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