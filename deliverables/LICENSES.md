# LICENSES.md

Last updated: 2026-06-03

Tracks third-party software, model weights, and data sources used by terra-mind, with their licenses.

## 1. Project License

terra-mind source code: **MIT** (set on the repository).

## 2. Data Source — Terraria Wiki

- **Source:** `https://terraria.wiki.gg` (the Official Terraria Wiki), accessed via the MediaWiki API.
- **Used for:** the RAG corpus (chunked + embedded into pgvector).
- **Content license:** **CC BY-NC-SA 4.0** — all textual content on the wiki is licensed Attribution-NonCommercial-ShareAlike 4.0 International.
- **Attribution:** preserved in each corpus chunk's metadata (source URL + page title) and in the corpus `manifest.json`.
- **Local cache:** raw scrape stored at `backend/data/raw/<version>/` — gitignored, not committed.

> **⚠️ License implication — read before any commercial framing.** CC BY-NC-SA 4.0 is **NonCommercial** and **ShareAlike**. For this academic submission (non-commercial, attributed) it is fine. But:
> - terra-mind **cannot be commercialized** as-is while its answers are derived from this corpus.
> - Any redistribution of the corpus or derived dataset inherits **ShareAlike** (must carry the same license).
> - The "SaaS" in the architecture describes the *multi-tenant design*, not a sellable product. This constraint is noted in `DECISIONS.md` and should be stated in the defense if the commercial angle comes up.

**Mods (e.g. Calamity):** out of scope (future work). Note for the record that mod content lives on separate wikis under different, often proprietary, licenses — another reason mod corpora are not a simple "version" addition.

## 3. Game Client Dependencies

| Component | Use | License / Status |
|---|---|---|
| Terraria | The game the mod runs in | Proprietary (Re-Logic). The mod requires the user to own a legitimate copy; nothing from the game is redistributed. |
| tModLoader | Modding framework / runtime | MIT (open source). |
| .NET 8 SDK | Mod build toolchain | MIT (.NET is MIT-licensed). |

## 4. Models

| Model | Use | License |
|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | RAG embeddings (local) | Apache-2.0 |
| Anthropic Claude (API) | Router, agent generation, class zero-shot, optional RAG judge | Anthropic commercial terms |

No fine-tuned or self-hosted generative weights (the trained class predictor is future work — D-009).

## 5. Python Dependencies

Top-level; final list confirmed in Phase 7.2.

| Package | Purpose | License |
|---|---|---|
| `fastapi` | API framework | MIT |
| `pydantic` | Schemas | MIT |
| `sqlalchemy` | ORM | MIT |
| `alembic` | Migrations | MIT |
| `fastapi-users` | Auth | MIT |
| `pgvector` (py) | Vector store client | MIT |
| `redis` | Short-term session memory | MIT |
| `hvac` | Vault client | Apache-2.0 |
| `anthropic` | LLM SDK | MIT |
| `langgraph` | Bounded agent loop | MIT |
| `langfuse` | Tracing | MIT |
| `sentence-transformers` | Local embeddings | Apache-2.0 |
| `httpx` | HTTP client (wiki scrape, modelserver-free) | BSD-3-Clause |
| `streamlit` | Admin/test UI | Apache-2.0 |
| `ruff` | Lint + format | MIT |
| `mypy` | Type-check | MIT |
| `pytest` | Tests | MIT |
| `ragas` (if used) | RAG generation eval | Apache-2.0 |

(Wiki scraping uses the MediaWiki API over `httpx`; if a MediaWiki client lib like `mwclient` (MIT) is adopted, add it here.)

## 6. JavaScript Dependencies (`frontend-user/`)

Confirmed in Phase 5.1.

| Package | Purpose | License |
|---|---|---|
| `react` | Config-portal UI | MIT |
| `react-dom` | Config-portal UI | MIT |
| `vite` | Bundler / dev server | MIT |

## 7. Infrastructure Images

| Image | License |
|---|---|
| `pgvector/pgvector:pg16` | PostgreSQL License (permissive) + pgvector (PostgreSQL License) |
| `redis:7-alpine` | BSD-3-Clause (pinned tag predates the RSALv2/SSPL relicensing) |
| `hashicorp/vault` (dev) | BSL-1.1 (used as a dev-mode local dependency, not redistributed) |
| `langfuse/langfuse` | MIT |

No `minio` (dropped — D-014). No `nginx` unless the React build is served via an nginx image; if so add `nginx` (BSD-2-Clause).