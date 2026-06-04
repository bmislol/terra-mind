# DECISIONS.md

Architectural decision log for **terra-mind**. Every significant choice lives here with its rationale and, where one exists, a number backing it. This is the source of truth that `CLAUDE.md`, `ARCH.md`, and the checklist reference.

**Conventions**
- Each decision has an ID (`D-NNN`), a status, the choice, the reasoning, and a number/evidence field.
- **Numbers that don't exist yet are marked `PENDING (measure)`** — they get filled from the golden set or a live measurement, never guessed.
- Decisions are revised **in place** with a dated revision note appended; IDs are never reused or deleted.
- Open questions we know we must answer live in **§ Pending Decisions** (`P-NNN`) and graduate into a `D-NNN` once settled.

---

## Locked Decisions

### D-001 — Layered backend architecture
**Status:** Locked (2026-06-03)
**Choice:** `api / services / repositories / domain / infra / db`, plus task subpackages `rag / agent / memory / guardrails / eval / prompts / core`.
**Why:** The layer split is graded ("the architecture is the grade"). Strict dependency direction (`api → services → repositories → db`; never reversed) keeps HTTP, business logic, and persistence independently testable. Inherited from the Week 7 layout, which held up under review.
**Number / evidence:** 6 core layers + 7 task packages; one allowed dependency direction. Layer-rule table in `ARCH.md §4`.

### D-002 — Mode, scope, and surfaces
**Status:** Locked (2026-06-03)
**Choice:** Solo developer. Multi-tenant SaaS backend, **demoed locally via `docker compose`**. The **singleplayer tModLoader client is the production chat surface** — it substitutes the web widget from the original brief.
**Why:** The approved brief was written with a three-owner split; this is one person on a 14-day clock, so scope is deliberately trimmed (see dropped items in D-009, D-010, D-014). Compose-local is the sane deploy target for the timeline; "SaaS" describes the architecture, not a hosted product.
**Number / evidence:** 1 developer; ~14 working days; target delivery 2026-06-18.

### D-003 — LLM provider
**Status:** Locked (2026-06-03)
**Choice:** Anthropic Claude only. `claude-haiku-4-5` as the router/agent default (latency-sensitive live advice), `claude-sonnet-4-6` reserved for harder reasoning if Haiku underperforms. Confirm current model availability before wiring.
**Why:** Single provider = one secret, one SDK, one eval surface. Haiku is the cheap/fast default because the player is waiting in-game for a reply.
**Number / evidence:** 2 model strings; latency budget target `PENDING (measure)`.

### D-004 — Embedding model
**Status:** Locked (2026-06-03)
**Choice:** `all-MiniLM-L6-v2`, **384-dim, run locally**. Pins the pgvector column to `vector(384)`. `bge-small-en-v1.5` is a drop-in re-embed if quality demands it.
**Why:** Embedding the full wiki (~4,800 pages, estimate) with a hosted API would cost per-call money for zero benefit on a public, static corpus; local MiniLM is free, fast, and a known quantity from Week 7.
**Number / evidence:** 384 dimensions; corpus size `PENDING (measure after scrape)`.

### D-005 — Vector store & corpus model
**Status:** Locked (2026-06-03)
**Choice:** pgvector on Postgres 16. The wiki corpus is **shared** across tenants and **tagged by `game_version`**; only player data is per-tenant.
**Why:** One database for relational + vector cuts an entire service. The wiki is public knowledge — re-embedding it per tenant would multiply cost/storage for nothing. Version tagging enables snapshot-forward switching (see brief §2.2).
**Number / evidence:** 1 shared corpus per version; index type → see P-002.

### D-006 — Tenancy & isolation
**Status:** Locked (2026-06-03)
**Choice:** Postgres Row-Level Security. Every player-data row carries `tenant_id`; the JWT sets the RLS context per request. The mod holds no API keys — it exchanges an identity for a short-lived signed JWT.
**Why:** RLS is the enforceable isolation story (Player A can never read Player B). DB-enforced beats app-enforced for a security-graded project.
**Number / evidence:** RLS on all tenant-scoped tables; JWT TTL `PENDING (measure)`; identity source → see P-005.

### D-007 — Secrets management
**Status:** Locked (2026-06-03)
**Choice:** HashiCorp Vault seeded by a `vault-init` service. Real secrets live only in an uncommitted `.env`; `.env.example` ships placeholders. Secret set: `anthropic.api_key`, `jwt.signing_key`.
**Why:** No secrets in git, ever. Refuse-to-boot if Vault is unreachable (D-015). Smaller secret set than Week 7 — no embedding-API key, since MiniLM is local.
**Number / evidence:** 2 secrets; redaction test proves no secret leaks to logs.

**Revised 2026-06-04:** Vault KV namespace locked to `secret/terra-mind/{anthropic,jwt}`. Fields: `api_key` (anthropic key) and `signing_key` (JWT key). These are the exact paths seeded by `vault-init` in Phase 1.4; `app/infra/vault.py` (Phase 1.5) must read from these paths. The original dotted notation (`anthropic.api_key`, `jwt.signing_key`) referred to logical names, not Vault paths — this revision makes the physical paths unambiguous.

### D-008 — Retrieval strategy
**Status:** Locked (2026-06-03)
**Choice:** **Dense-only first.** Add BM25/hybrid (RRF) **only if** dense underperforms on the golden set, recorded as a number-backed escalation. **No HyDE.**
**Why:** Player-state extraction and retrieval are orthogonal — state makes the *answer* contextual, retrieval decides whether the right facts are *available*. Start simple, escalate on evidence. HyDE adds one LLM call per query and is rejected on latency grounds for live advice.
**Number / evidence:** dense hit@k baseline `PENDING (measure)`; escalation trigger = dense hit@5 below threshold (P-003).

### D-009 — Class detection
**Status:** Locked (2026-06-03)
**Choice:** Primary = read **equipped gear live** in-game (armor set + held weapon + accessories). Cold-start fallback = **LLM zero-shot** on the onboarding questionnaire. Trained classifier → **future work**.
**Why:** Equipped gear is *truthful*, not predicted — a full ranger set holding a Megashark *is* a ranger. The trained model would need a synthetic, wiki-grounded dataset (no labelled "answers→class" rows exist), making its F1 circular; not worth the days.
**Number / evidence:** 4 classes (Melee/Ranger/Mage/Summoner); 0 training rows required.

### D-010 — Memory
**Status:** Locked (2026-06-03)
**Choice:** **Short-term Redis with explicit TTL only.** No long-term / cross-conversation memory.
**Why:** Survival advice is session-scoped; there's no product need to recall last week's session. Dropping long-term memory removes the audit-logged pgvector write path Week 7 carried — pure scope saved.
**Number / evidence:** session TTL value → see P-004.

### D-011 — Frontends
**Status:** Locked (2026-06-03)
**Choice:** `frontend-user/` (React + Vite) = **config portal** (login/guest, version select + check, preferences, right-to-erasure). `frontend-admin/` (Streamlit) = **operator + test bench** (corpus/version management, re-rag trigger, tenant view, test chat). **No** embeddable widget, **no** `demo/host/`.
**Why:** The game client is the only chat surface a player sees — the React app configures, it does not chat. The widget/host/blocked-host services from Week 7 existed only to demo an embeddable widget's CORS/`frame-ancestors` story, which no longer exists here.
**Number / evidence:** 2 web surfaces + 1 game surface. Portal kept minimal (forms only) so it can degrade to a Streamlit page if the clock tightens.

### D-012 — Guardrails
**Status:** Locked (2026-06-03)
**Choice:** Lightweight **deterministic + LLM-judge** filter against prompt injection, progression jailbreaks ("give me dev items"), and toxicity. **NeMo Guardrails = stretch only.**
**Why:** The graded requirement is "red-team injection attempts fail the CI build" — satisfiable with a lighter layer. NeMo is notoriously fiddly to stand up and not worth the critical-path risk.
**Number / evidence:** red-team set size + pass criteria → see P-006; gate = 0 successful injections for green build.

### D-013 — Tracing / observability
**Status:** Locked (2026-06-03)
**Choice:** Langfuse, self-hosted in compose.
**Why:** A bounded LangGraph agent loop is miserable to debug and weak to demo without trace visibility; "traces are real" was a graded line in Week 7. Already stood up once — known quantity. Cost is its own Postgres database in compose, accepted.
**Number / evidence:** every agent run produces a visible trace tree.

### D-014 — Blob storage
**Status:** Locked (2026-06-03) — **dropped**
**Choice:** **No MinIO.** Raw scraped corpus lives on a gitignored volume (`data/corpus/<version>/`).
**Why:** Week 7's MinIO held model artifacts; the trained model is now future work (D-009), so that justification is gone. The only remaining reason would be SHA-pinned corpus snapshots for reproducible re-rag — a "nice to have," not a need, and adding an unused service violates the "justify every library" rule. Considered and deferred deliberately.
**Number / evidence:** 1 fewer service than Week 7.

### D-015 — Tooling & engineering conventions
**Status:** Locked (2026-06-03)
**Choice:** `uv` for packaging; `ruff` + `ruff format` + `mypy` + `pytest` all green locally before push; conventional commits; squash merge; one-phase-per-branch (`feat/<NN>-<slug>`); refuse-to-boot on misconfigured dependencies (Vault, eval thresholds).
**Why:** Carried over wholesale from Week 7 — it worked, and it's the cheap, high-grading-value discipline.
**Number / evidence:** 4 local CI gates; 1 phase per branch.

### D-016 — Game-version & SDK targets
**Status:** Locked (2026-06-03)
**Choice:** Target the Terraria version **tModLoader's stable branch currently supports** (confirm before scraping — current desktop Terraria is 1.4.5, but tModLoader may lag). Mod toolchain = **.NET 8 SDK** (not 9/10).
**Why:** The mod runs on tModLoader, not bare Terraria, so the corpus must match tModLoader's supported version. .NET 8 is what current tModLoader requires; 9/10 are rejected by its targets.
**Number / evidence:** .NET 8.0; corpus `game_version` tag set to confirmed value at scrape time.

**Revised 2026-06-03:** Target version confirmed as **Terraria 1.4.4.9**. tModLoader v2026.4.3.0 (current stable) targets 1.4.4.9; current bare Terraria desktop is 1.4.5, but the mod runs on tModLoader which lags bare Terraria — this confirms the original rationale. The corpus `game_version` tag is `1.4.4.9`. "Confirm before scraping" is resolved; no further version discovery needed.

### D-017 — audit_log RLS exemption + terramind_app role split
**Status:** Locked (2026-06-04)
**Choice:** (a) `audit_log` has RLS **disabled**; access is enforced by the `is_superuser` gate in the service layer. (b) The API connects as `terramind_app` (non-superuser, non-owner); `terramind` (superuser owner) is used only by `migrate`.
**Why:** (a) `audit_log` is cross-tenant by design — an operator must read rows across all tenants (SECURITY.md §6). A row-level policy would require a DB-level operator concept (a third Postgres role or a session variable mirroring `is_superuser`) that duplicates the service layer's role model for no isolation benefit. The service layer `current_active_superuser` dependency is the correct control boundary. (b) A superuser connection bypasses RLS unconditionally regardless of `ENABLE ROW LEVEL SECURITY` or `FORCE ROW LEVEL SECURITY` — the only correct fix is a non-superuser role. `terramind_app` is created by `postgres-init.sh` on fresh volume init; `migrate` connects as `terramind` to create tables and grant, then `api` connects as `terramind_app`.
**Number / evidence:** 2 Postgres roles; 2 tables with RLS (`sessions`, `messages`); 1 intentional RLS exemption (`audit_log`).

---

## Pending Decisions

Open questions we know we must answer. Each graduates to a `D-NNN` once settled, **with a number**.

| ID | Question | Decide during | Number it will be backed by |
|---|---|---|---|
| P-001 | Wiki chunking strategy (structural by section/infobox vs sliding-window vs hybrid) | RAG phase | hit@k delta on golden set |
| P-002 | pgvector index type + params (HNSW vs IVFFlat; `m`/`ef` or `lists`) | corpus-build phase | recall vs query-latency at corpus scale |
| P-003 | RAG eval thresholds (hit@k floor, possibly MRR@10) | after baseline measurement | measured baseline on the 15 golden questions |
| P-004 | Redis session TTL value | memory phase | session-length distribution / defended choice |
| P-005 | **Singleplayer tenant identity** — what the mod exchanges for a JWT when there is no multiplayer server ID | auth + client phase | n/a (design decision; documented rationale) |
| P-006 | Guardrail rule set, LLM-judge prompt, and red-team set composition | guardrails phase | red-team pass rate (target: 0 successful injections) |
| P-007 | Whether to escalate to hybrid retrieval (depends on D-008) | after P-003 | dense vs dense+BM25 hit@k |
| P-008 | Agent tool set finalization + bounded-loop iteration cap | agent phase | max iterations (a number) + tool count |

---

## Revision Log

- **2026-06-03 · D-016:** Confirmed Terraria target version as 1.4.4.9 (tModLoader v2026.4.3.0). Corpus `game_version` tag locked to `1.4.4.9`. "Confirm before scraping" placeholder resolved.
- **2026-06-04 · D-007:** Locked Vault KV paths to `secret/terra-mind/anthropic` (`api_key`) and `secret/terra-mind/jwt` (`signing_key`). Logical dotted names in original decision now mapped to concrete physical paths seeded by vault-init.
- **2026-06-04 · D-017 (new):** audit_log RLS exemption and terramind_app role split locked. API connects as terramind_app (non-superuser); migrate connects as terramind (owner). audit_log has no RLS — operator-gated at the service layer.