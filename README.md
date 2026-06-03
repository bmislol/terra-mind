# terra-mind

A multi-tenant AI companion for Terraria. It connects a singleplayer C# tModLoader client to a Python/FastAPI backend, using pgvector and LangGraph for live-state agentic workflows and RAG over the Terraria wiki.

> **Status:** early development. The repository is being built phase-by-phase (see `Checklist.md`); most components are scaffolding at this stage.

## What it does

A player asks a question from inside Terraria with `/bot <question>`. The mod reads their **live character and world state** — equipped gear, inventory, defeated bosses, hardmode status, biome — and sends it with the question to the backend. The backend retrieves the relevant Terraria wiki facts and answers with **progression-aware** survival advice, instead of a flat wiki lookup. Detecting that you're a pre-mechanical-boss ranger with no wings changes the answer.

## Architecture

Three surfaces over one FastAPI backend:

- **Game client (`client/`)** — singleplayer tModLoader mod. The production chat surface (`/bot`).
- **Config portal (`frontend-user/`)** — React + Vite. Login / guest / preferences / version selection / data erasure. Not a chat surface.
- **Admin bench (`frontend-admin/`)** — Streamlit. Operator tooling: corpus & version management, re-rag, tenant view, test chat.

Tenant isolation is enforced with Postgres Row-Level Security; a short-lived JWT carries the `tenant_id`. The wiki corpus is shared and version-tagged — only player data is per-tenant.

## Stack

FastAPI · Postgres 16 + pgvector · Redis · HashiCorp Vault · Langfuse · LangGraph · `all-MiniLM-L6-v2` (local embeddings) · Anthropic Claude · C# / tModLoader (.NET 8) · React + Vite · Streamlit · `uv` · Docker Compose.

## Getting started

The full stack runs locally via Docker Compose. See **`deliverables/RUNBOOK.md §1`** for first-time startup, and §4 for building the wiki corpus.

```bash
cp .env.example .env
docker compose up --build
```

## Project documentation

| Doc | Purpose |
|---|---|
| `CLAUDE.md` | Working guide / index for collaborators. |
| `Checklist.md` | Phase-by-phase build progress. |
| `deliverables/ARCH.md` | System design, layer rules, data flow. |
| `deliverables/DECISIONS.md` | Architectural decisions, each backed by a number. |
| `deliverables/RUNBOOK.md` | Startup, refuse-to-boot, evals, demo. |
| `deliverables/EVALS.md` | RAG and red-team gates. |
| `deliverables/SECURITY.md` | Tenant isolation, auth, guardrails. |
| `deliverables/LICENSES.md` | Third-party licenses and data-source terms. |

## License

Source code: **MIT** (see `LICENSE`).

Wiki content used for the RAG corpus is from the Official Terraria Wiki under **CC BY-NC-SA 4.0**. Note the **NonCommercial** clause: this project is an academic, non-commercial work and is not licensed for commercial use while its answers derive from that corpus. See `deliverables/LICENSES.md §2`.

Built as the final project for the AIE Program.