# TerraMind — Operator / Test Bench (`frontend-admin/`)

Streamlit operator bench + the **demo fallback** (RUNBOOK §7.1). Functional, not
polished. All API calls are **server-side** (httpx from the Streamlit process),
so no CORS applies.

## What it does (operator-gated)
- **Test chat (centerpiece):** pick a preset character state (melee pre-boss /
  ranger post-EoC / mage hardmode) + a question → `POST /bot/ask` → renders the
  answer, the **routing** (faq/agent), and the session_id, and shows the **raw
  StatePayload** sent. The full pipeline, no Terraria — the fallback if the live
  game won't launch in the demo.
- **Versions:** stored corpus versions via `GET /versions` (+ the re-rag script note, P-019).
- **Tenants / Audit:** the operator views `GET /admin/tenants` + `GET /admin/audit-log`.

A **player** account can log in but is blocked from the bench — the real gate is
the backend (`require_operator` → 403 on `/admin/*`); the UI just hides it.

## Bootstrap an operator first (you need one to log in)
The bench requires an operator account. Create one host-side (RUNBOOK §3) with
the stack up:

```bash
cd backend
export BOOTSTRAP_EMAIL="operator@terra-mind.dev"
export BOOTSTRAP_PASSWORD="change-me-before-demo"
export DATABASE_URL="postgresql+asyncpg://terramind:terramind-dev-password@localhost:5432/terramind"
uv run python -m app.entrypoints.bootstrap_operator
# → "operator created: operator@terra-mind.dev"   (idempotent — safe to re-run)
```

## Run with the stack (Docker)
```bash
docker compose up -d --build api frontend-admin
# bench → http://localhost:8501    (calls the API server-side at http://api:8000)
```

## Run locally (dev)
```bash
cd frontend-admin
pip install -r requirements.txt
API_BASE_URL=http://localhost:8000 streamlit run app.py   # → http://localhost:8501
```
`API_BASE_URL` defaults to `http://localhost:8000`; compose sets `http://api:8000`.
