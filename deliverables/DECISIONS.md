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
**Number / evidence:** RLS on all tenant-scoped tables; JWT TTLs locked (D-029): **access 30 min, refresh 30 days**; identity source → P-005, resolved by D-027.

**Revised 2026-06-14 (Phase 4.1a):** "JWT TTL PENDING (measure)" graduated to two **server-pinned** values (D-029): **access = 30 min**, **refresh = 30 days**. Rationale: the 30-min access token bounds the leak-damage window (a stolen access token dies within 30 min) while avoiding constant refresh on the latency-critical live-advice path; the 30-day refresh token means "stay logged in a month" and is revocable via the denylist (D-029). Both are server-set, **not** user-configurable — a TTL is a security boundary, not a preference.

### D-007 — Secrets management
**Status:** Locked (2026-06-03)
**Choice:** HashiCorp Vault seeded by a `vault-init` service. Real secrets live only in an uncommitted `.env`; `.env.example` ships placeholders. Secret set: `anthropic.api_key`, `jwt.signing_key`.
**Why:** No secrets in git, ever. Refuse-to-boot if Vault is unreachable (D-015). Smaller secret set than Week 7 — no embedding-API key, since MiniLM is local.
**Number / evidence:** 2 secrets; redaction test proves no secret leaks to logs.

**Revised 2026-06-04 (Phase 1.4):** Vault KV namespace locked to `secret/terra-mind/{anthropic,jwt}`. Fields: `api_key` (anthropic key) and `signing_key` (JWT key). These are the exact paths seeded by `vault-init` in Phase 1.4; `app/infra/vault.py` (Phase 1.5) must read from these paths. The original dotted notation (`anthropic.api_key`, `jwt.signing_key`) referred to logical names, not Vault paths — this revision makes the physical paths unambiguous.

**Revised 2026-06-04 (Phase 1.6):** Langfuse credentials (`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SDK_SECRET_KEY`) come from env, not Vault. These are self-hosted infrastructure credentials (project API keys seeded via `LANGFUSE_INIT_PROJECT_*`), not application secrets like the Anthropic key. Adding them to Vault would create a circular dependency (Vault seeder needs Langfuse up; Langfuse needs to be healthy before Vault seeds) and provides no security benefit in a dev-local stack.

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

**Revised 2026-06-13 (Phase 3.3):** Fully implemented — see **D-026** (hybrid Cargo `damagetype` + curated armor map + LLM zero-shot fallback). Trained classifier confirmed not needed.

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

### D-018 — Chunking strategy
**Status:** Locked (2026-06-05, Phase 2.2)
**Choice:** Hybrid structural + sliding-window + Cargo template synthesis.
- Wikitext split at L2 headings via mwparserfromhell `get_sections(levels=[2])`; `strip_code()` for plain text.
- Token budget: 180-token target window (MiniLM's 256-token context − 76-token buffer for prepend + special tokens), 30-token overlap, 20-token minimum.
- Prepend: `"{page_title} — {section_heading}\n"` on every chunk's embed text.
- Cargo Items synthesis: `section="stats"` chunk from Cargo Items row (damage, usetime, knockback, velocity, critical, defense, mana, tooltip). Use-time labels from wiki-sourced thresholds (≤8 Insanely fast … ≥56 Snail).
- Cargo Recipes synthesis: `section="recipe"` chunk per Recipes row; args parsed via U+00A6 BROKEN BAR separator.
- NPC synthesis: `section="stats"` + `section="drops"` from wikitext `{{npc infobox}}` template; Classic-mode damage/defense via `{{modes}}` first-positional extraction.
- Cargo tables scraped: **Items** and **Recipes** only. NPCs, Drops, History, Equipinfo, Modifiers, Weapon_source, Exclusive, Imageinfo explicitly rejected (redundant with wikitext extraction or outside scope).
**Why:** Item stats are Cargo-only (all item pages use `{{item infobox | auto = NNN}}` with no literal damage params); wikitext wikitext-only approach left ~3,800 item pages with no stats chunk. Cargo integration closes this gap without re-scraping. Recipe data (4,221 rows) is not in wikitext at all. NPC pages have Classic-mode stats in `{{modes}}` template args and are already extractable.
**Number / evidence (measured 2026-06-05, `game_version=1.4.4.9`):**

| Metric | Value |
|---|---|
| Total chunks | **22,173** |
| Distinct pages with ≥1 chunk | 4,534 of 5,157 (623 pages → empty after stripping: disambiguations + purely template pages) |
| Distinct section labels | **29** (down from 1,329 before `_normalize_section_name`) |
| Cargo stats chunks (`section="stats"`, Items rows) | 2,808 across 2,771 pages |
| Recipe chunks (`section="recipe"`) | 1,590 |
| NPC drop chunks (`section="drops"`) | 170 |
| Intro prose chunks (`section="intro"`) | 5,278 |
| Misc chunks (normalised non-English headings) | 5,962 |
| Notes / Trivia / Tips prose | 2,133 / 2,041 / 1,788 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2`, 384-dim |
| Build wall time | ~1:40 (model cached) / ~2:00 (first run) |

**Join-key characteristics (not bugs — structural properties of the wiki):**
- 3,462 of 6,233 Cargo Items rows (54%) have no matching wiki page: internal IDs, tile variants, sub-items without standalone pages. These Cargo rows produce no chunks.
- 2,631 of 4,221 Recipes rows (62%) have a `result` that doesn't match any wiki page. Logged to `cargo/orphan_recipes.jsonl`. Same cause: recipe register pages reference item IDs that the wiki doesn't expose as standalone articles.
- Phase 2.4 hit@k measurement will surface whether these join gaps hurt retrieval. If so, a follow-up phase queries the wiki redirect API to resolve canonical names — not a Phase 2.2 task.

### D-019 — pgvector index (graduated from P-002)
**Status:** Locked (2026-06-05, Phase 2.2)
**Choice:** HNSW, `m=16`, `ef_construction=64`, `vector_cosine_ops` on `rag_chunks(embedding)`.
**Why:** At ~20k–50k chunks, HNSW at `ef_search=40` gives >99% recall@10 vs IVFFlat's ~90% (searching `lists/10` probe lists at `lists≈sqrt(n)`). For dense-only retrieval (D-008) with no BM25 fallback, that ~10% miss rate is material. Build time at this corpus size is seconds. Memory overhead: ~6–15 MB. MiniLM outputs L2-normalised embeddings; cosine distance equals inner product — `vector_cosine_ops` is correct.
**Number / evidence (Phase 2.4, measured 2026-06-06):**

| Metric | Measured |
|---|---|
| hit@5 (primary gate) | 0.667 (10/15 questions) |
| hit@10 | 0.867 (13/15 questions) |
| MRR@10 | 0.576 |
| Median retrieve() latency | 5.6 ms |
| p95 retrieve() latency | 175.8 ms (first-call PyTorch JIT warmup; steady-state p95 ≈ 15 ms) |

Thresholds set per D-020 formula. Two questions (Q11, Q15) are complete misses due to entity-naming gaps; see EVALS.md §1.6.

---

### D-020 — RAG eval thresholds (graduated from P-003)
**Status:** Locked (2026-06-06, Phase 2.4)
**Choice:** Committed thresholds in `eval_thresholds.yaml`:

| Key | Threshold | Baseline | Derivation |
|---|---|---|---|
| `hit_at_1_min` | 0.35 | 0.467 | floor(0.467×10)/10 − 0.05 |
| `hit_at_k_min` (hit@5, primary gate) | 0.55 | 0.667 | floor(0.667×10)/10 − 0.05 |
| `mrr_at_10_min` | 0.45 | 0.576 | floor(0.576×10)/10 − 0.05 |
| `p95_latency_ms_max` | 300 ms | 175.8 ms | baseline × 1.75 (75% headroom) |

**Threshold derivation formula:** `threshold = floor(baseline × 10) / 10 − 0.05`. The `floor(×10)/10` step rounds down to the nearest 0.1, then subtracts 0.05. This gives 5–10 percentage points of headroom below the measured baseline to absorb HNSW non-determinism and minor embedding-model version drift without masking real regressions (a regression that drops hit@5 by ≥ 0.10 turns CI red).

**Why these numbers and not the baseline itself:** setting the threshold equal to the baseline would cause CI to fail on any tiny variance (HNSW approximate search is non-deterministic by design at the same `ef_search`). The headroom must be meaningful (enough to tolerate noise) but not so wide as to hide real regressions. 0.05 (5 percentage points) was validated against the observed MiniLM embedding variance in similar corpora.

**Latency note:** The 300 ms p95 ceiling is calibrated to local development where the harness starts fresh and the first PyTorch JIT warmup takes ~175 ms. Steady-state p95 after warmup is ~15 ms. The ceiling may need recalibration after the first eval-rag.yml CI run on GitHub-hosted runners (different hardware characteristics).

**Number / evidence:** Measured on corpus version 1.4.4.9, 22,173 chunks, HNSW m=16 ef_construction=64 ef_search=40 (pgvector default), `all-MiniLM-L6-v2` 384-dim, 15 golden questions from `backend/data/eval/eval_rag.jsonl`.

### D-021 — Deterministic chunk IDs
**Status:** Locked (2026-06-06, Phase 2.5)
**Choice:** `rag_chunks.id` is set to `uuid5(NAMESPACE_OID, f"{page_id}:{chunk_index}:{game_version}")`. `NAMESPACE_OID` is the stdlib constant `uuid.NAMESPACE_OID` (`6ba7b812-9dad-11d1-80b4-00c04fd430c8`); no custom namespace UUID is used.
**Why:** Phase 2.4 closeout revealed that `id = uuid4()` (previously used in `build_corpus.py`) is random on every INSERT. After `docker compose down -v`, a fresh corpus rebuild produced all-new random UUIDs, silently invalidating the golden set's `ground_truth_chunks`. The symptom was discovered in PR #11 (fix/golden-set-uuids), which patched the JSONL by hand. Phase 2.5 makes the root cause impossible: `uuid5` over the natural key `(page_id:chunk_index:game_version)` produces the same UUID for the same chunk on every build, forever. The application supplies `id` explicitly on every INSERT; no DB DEFAULT exists, so no Alembic migration was needed — TRUNCATE + rebuild was sufficient.
**Number / evidence:** `chunk_id(page_id=42, chunk_index=3, game_version="1.4.4.9")` returns the identical UUID across two independent calls. STEP 6 of Phase 2.5 verification: `down -v` + fresh rebuild reproduced hit@5=0.667 with the same `eval_rag.jsonl` on disk (no refresh script run), proving the contract holds.
**Migration:** one-time `scripts/refresh_golden_set.py` run against the pre-rebuild DB rewrites `data/eval/eval_rag.jsonl` with the stable UUIDs. After that run, the golden set never needs UUID refresh again.

### D-022 — Threshold direction convention
**Status:** Locked (2026-06-06, Phase 2.5)
**Choice:** Threshold keys in `eval_thresholds.yaml` encode their comparison direction in their suffix:
- `_min` → lower-bound floor: `measured >= threshold` passes.
- `_max` → upper-bound ceiling: `measured <= threshold` passes.
- Any other suffix → `ValueError` raised at evaluation time (loud failure for future contributors adding new keys).

Implemented in `app/core/threshold_directions.py` (shared between the harness and the refuse-to-boot check). A `_min` or `_max` key set to `0` is also rejected at boot time (`zero_is_valid_for_key()` returns False for these), because a quality floor of 0 means "no gate." Keys with neither suffix (e.g. `redteam.max_successful_injections`) are exempt from the zero check — 0 is a valid strict floor there.
**Why:** Phase 2.4 revealed a latent bug: `harness.py::_check` used `measured < threshold` for all keys. For `p95_latency_ms_max: 300`, a 164 ms measurement yielded `164 < 300 → True → FAILURE`. The bug was latent (eval-rag.yml is manual-dispatch, not PR-gated) but would have reported every passing latency run as a failure. The suffix convention makes direction self-documenting in the YAML key name and makes the rule machine-checked rather than comment-enforced.
**Number / evidence:** 4 threshold keys in production YAML — 3 use `_min`, 1 uses `_max`. Unit tests in `tests/eval/rag/test_harness.py` lock the at-threshold boundary (pass) and past-threshold boundary (fail) for both directions.

### D-023 — Router and FAQ model selection
**Status:** Locked (2026-06-11, Phase 3.1)
**Choice:** `claude-haiku-4-5` for both the classifier router and the FAQ answer synthesis (D-003 default). `claude-sonnet-4-6` reserved for Phase 3.2 if Haiku underperforms on multi-step agent reasoning.
**Why:** The router call produces a single token (`"faq"` or `"agent"`) — there is no scenario where a more capable model is warranted for a binary classification that Haiku handles correctly on every test query. The FAQ synthesis is similarly constrained: one retrieved chunk, a 2–4-sentence answer, and the `faq_answer.md` system prompt. Haiku's output quality matches the contract without escalating cost or latency. Latency is the binding constraint: a player is waiting in-game for a reply on every `/bot` turn, and Haiku has ~3× lower latency than Sonnet under identical token budgets.
**Number / evidence (measured 2026-06-11 smoke test, `game_version=1.4.4.9`):**

| Call | Model | Input tokens | Output tokens | Approx. cost per request |
|---|---|---|---|---|
| Router classify | `claude-haiku-4-5` | ~80 | ~2 | ~$0.00001 |
| FAQ answer synthesis | `claude-haiku-4-5` | ~200 | ~80 | ~$0.0007 |
| Agent stub (no LLM call) | n/a | 0 | 0 | ~$0.0 |

Two-request smoke test total (`"What damage does the Megashark do?"` + `"Why do I keep dying to Skeletron?"`): ~$0.001. Token budget matches pre-phase projections. Sonnet-4-6 upgrade path left open at the Phase 3.2 agent boundary (P-008 covers the loop budget).

### D-024 — Agent bounded-loop iteration cap (graduated from P-008)
**Status:** Locked (2026-06-12, Phase 3.2)
**Choice:** `MAX_ITERATIONS = 5` in `app/agent/graph.py`. The bounded LangGraph loop is `START → plan → (execute_tools | END)`; `execute_tools → (plan | synthesize_cap)`; the cap bounds the number of `plan → execute_tools` cycles. Tool roster finalized at **three**: `query_wiki` (version-filtered RAG, D-008), `analyze_loadout` (reads the state payload, hardcoded item→class dict in 3.2 → Cargo-aware in 3.3 per D-009), `suggest_next_boss` (deterministic progression tree). This resolves both halves of P-008 — tool-set finalization and the iteration cap.
**Why:** Empirically **1–3 iterations suffice for all 10 tested hard questions** (Phase 3.2 eval run, 12 Jun 2026); 5 gives conservative headroom without uncontrolled cost. Worst case is 6 LLM calls per turn (5 planning calls + 1 forced `synthesize_cap` synthesis), ~$0.01–0.02 (D-025).
**Important caveat — cap semantics (document explicitly):** `MAX_ITERATIONS` bounds the `plan → execute_tools` **cycle** count, **not** the total number of tool dispatches. `execute_tools` dispatches *every* `tool_use` block present in a single assistant message and increments `iteration_count` by exactly 1 per node visit — so one iteration can fan out to multiple tool calls. Total tool dispatches per `/bot/ask` can therefore exceed 5: in the eval set **Q05** (Summoner vs Moon Lord, full late-game state) accumulated 30 chunks = **6 `query_wiki` dispatches within ≤ 5 iterations**.
**Future polish (P-012):** if per-call cost becomes a concern, add a separate cap on total `chunks_seen` length (or a token ceiling) to bound the largest possible context size — the dominant cost driver per D-025, which `MAX_ITERATIONS` alone does not bound.
**Number / evidence:** MAX_ITERATIONS=5; 3 tools; 1–3 iterations observed across 10 eval questions; worst observed 6 tool dispatches (Q05). Recommendation after measurement: **keep 5**.

### D-025 — Agent cost & latency profile
**Status:** Locked (2026-06-12, Phase 3.2)
**Choice / finding:** Measured profile of the agent path (`claude-haiku-4-5`, D-023) from the 10-question evaluation run (`scripts/measure_agent_cost.py`, 12 Jun 2026 16:42 UTC).
**Number / evidence (measured 2026-06-12, `game_version=1.4.4.9`):**

| Metric | Value |
|---|---|
| Total cost, 10 agent calls | $0.07–0.09 |
| Median cost per `/bot/ask` | ~$0.005 |
| p95 cost per `/bot/ask` | ~$0.020 (Q05, cap-pressing summoner question) |
| Median latency | ~7 s |
| p95 latency | ~13 s (Q05) |
| Anthropic console totals over the run | 66,832 input tok / 4,105 output tok |

Per-question chunk accumulation / `query_wiki` dispatches / latency: **Q05** 30/6/12.7s · **Q11** 15/3/8.1s · **Q07** 15/3/9.7s · **Q09** 15/3/9.6s · **Q10** 10/2/8.6s · **Q03** 5/1/6.1s · **Q04** 5/1/4.6s · **Q15** 0/0 (`suggest_next_boss` only, no wiki retrieval)/4.6s · **Q06** 0/0/4.1s · **Q08** routed to FAQ (1 chunk, 2.1s) — confirms the router sends a pure recipe question to the deterministic path even with state present. Q15's empty `source_chunks` is expected behaviour, not a bug: the agent answered the progression question from `suggest_next_boss` + LLM knowledge without a `query_wiki` call on that turn.
**Cost methodology:** exact per-trace token counts are **unavailable in the Langfuse UI (P-009)**; cost is computed from the Anthropic console total token delta over the run at Haiku pricing ($0.80/M input + $4.00/M output, D-023). The credit-balance delta for the day was $13.77 → $13.68 = $0.09, of which ~$0.07 is the run itself (token-derived) and the remainder is same-day smoke-test overhead. `AnthropicClient` receives correct counts from the SDK — only the Langfuse display is affected.
**Token-cost growth:** input cost grows roughly **linear-to-quadratic with iteration count** — each subsequent planning call re-sends the accumulated tool results (chunk text) as context, so input tokens compound across iterations. This is why a cap on `chunks_seen` length (P-012) is the natural cost lever, not just the iteration count.

### D-026 — Hybrid class detection (graduates D-009 to implemented)
**Status:** Locked (2026-06-13, Phase 3.3)
**Choice:** Player class is detected by a three-tier hybrid, resolved per equipped item by `ItemClassifier` (`app/agent/class_detection.py`) with a deterministic vote across all gear in `analyze_loadout`:
1. **Cargo weapons** — class from the Cargo Items `damagetype` field (`Melee`/`Ranged`/`Magic`/`Summon`, case-normalised), **gated on `type` containing `"weapon"`** so tools/ammunition that also carry a `damagetype` (pickaxes, bullets) are excluded (finding A2). Indexed by `item_id` and by `name`.
2. **Curated armor/fallback map** — `CURATED_ITEM_CLASS` (the demoted Phase 3.2 dict), because the Cargo Items table carries **zero class signal for armor** (finding A3: every armor row has empty `damagetype`/`tag`, `type=armor`, generic `listcat="craftable items"`). Also the fallback for weapons not in Cargo.
3. **LLM zero-shot fallback** — when both deterministic tiers find no signal (empty/unknown/mixed gear → `needs_llm_fallback=True`), `execute_tools` fires one `claude-haiku-4-5` call (`max_tokens=8`, system prompt `class_fallback.md`) over a name-based gear+inventory summary. Fires in `execute_tools`, **never inside `analyze_loadout`** (which stays a pure, LLM-free function so its fixtures keep returning `class=None`).

**Resolution order per item:** `item_id → Cargo weapon` → `name → Cargo weapon` → `item_id → Cargo name → curated` (armor bridge for mod item_ids) → `name → curated` → `None`. `item_id` is primary because it is mod-native (`item.type` == Cargo `itemid`) and localization-stable; `name` is the fallback for hand-entered / test payloads.

**Number / evidence (measured 2026-06-13, `game_version=1.4.4.9`, `items.json` = 6,233 rows):**

| Signal source | Coverage |
|---|---|
| Cargo weapons via `damagetype`, **gated on type=weapon (A2)** | **446** rows = 198 melee + 113 ranger + 76 magic + 59 summoner → **445 distinct item_ids** |
| Rows carrying a class `damagetype` *before* gating | 632 — A2 excludes **186 tools/ammunition** (pickaxes are `damagetype=Melee`, bullets `damagetype=Ranged`); counting them would misclassify a pickaxe as melee |
| vs Phase 3.2 hardcoded dict (~20 weapons) | **~22× weapon coverage** |
| Armor class signal in Cargo | **0** — 100% of armor resolves via the curated map (A3) |
| LLM zero-shot fallback cost | ~$0.0002/call (~80 in / 8 out, Haiku), cold-start only |

**Multi-tag note:** the `^`-joined multi-tag is on the Cargo **`type`** field (`"weapon^crafting material"`, e.g. Minishark) — **not** on `damagetype`, which is always clean. `_is_weapon_type` splits `type` on `^` and checks for a `weapon` segment; the **446 count is unchanged** vs the prior substring check (verified — 0 disagreements on real data). Unlike `listcat` (rejected in A1 for being unusably multi-tag), `damagetype` has no `^`, so no `damagetype` parser is needed.

**Cost addendum (NOT in D-025's Phase 3.2 profile):** the fallback adds one extra `claude-haiku-4-5` call (~$0.0002, ~1–2 s latency) to **any agent turn where deterministic detection finds no class signal** (empty / unknown / mixed gear). It does **not** fire when the player has a clear class lean. This is new spend beyond the D-025 agent profile; cold-start path only.

**CI / data constraint (finding A4):** `data/raw/` is gitignored, so the Cargo `items.json` is **not present in CI**. The module-level `DEFAULT_CLASSIFIER` is curated-only (no Cargo) and is what unit tests resolve against; production layers Cargo on at lifespan via `ItemClassifier.from_cargo_file` (refuse-to-boot if missing, unparseable, or `< 100` rows). Cargo-path tests use a small **synthetic** `items.json` fixture. **Tests must not boot the real lifespan in CI** — the `min_items=100` check would refuse-to-boot without the gitignored file.

**Graduates D-009:** the live gear-read + LLM zero-shot cold-start of D-009 is now fully implemented. The trained-classifier path is **confirmed future-work-not-needed** — truthful gear read + Cargo `damagetype` + LLM zero-shot covers the four classes with no labelled dataset. The 8 `analyze_loadout` + 9 `suggest_next_boss` fixtures pass unchanged across the swap (the curated map is byte-identical to the Phase 3.2 dict).

### D-027 — Game-client identity & mod login (graduates P-005)
**Status:** Locked (2026-06-14, Section 4 planning)
**Choice:** The singleplayer mod authenticates as a **player account via a login-once / token-persist** flow (refined Option A of P-005):
1. **Login once.** On first launch (config-driven; an in-game UI panel is a Section 7 polish stretch) the mod takes a username + password, POSTs them to `POST /auth/jwt/login`, and **immediately discards the password** — it is never written to disk or kept in memory beyond the request.
2. **Persist the token.** The mod saves the returned **refresh** token in its config dir (browser-cookie style). On every launch it exchanges that saved token at `POST /auth/refresh` for a **short-lived access JWT** (which carries `tenant_id` + role and is the RLS-context source, D-006/D-029). The player stays logged in across Terraria restarts with no re-typing.
3. **Logout.** A `/bot logout` command (or config toggle) deletes the saved token locally **and** invalidates it server-side (denylist, D-029), forcing re-login on the next launch.
4. **Registration is portal-only** (`POST /auth/register` via the React portal, D-011) — never through the mod.

**Revised 2026-06-14 (Phase 4.1a):** the access+refresh split (D-029) makes the mod's "exchange saved token for a JWT" identical to refresh→access, so `/client/token` was **dropped and folded into `POST /auth/refresh`** — the mod saves the refresh token and calls `/auth/refresh`. One endpoint, one code path.

**Why (security rationale):** the mod **never holds the password** (transmitted once, then discarded) **and never holds an API key** — it holds only a revocable account token that exchanges for a short-lived JWT. This avoids storing a password in a plaintext mod config (the core rationale for typed-once-then-discard). A leaked token compromises exactly one account and is rotatable from the portal / killable via D-029. The one password transmission must be over HTTPS in any hosted setup; the `localhost` default (D-028) is in-machine, so plaintext there is a non-issue (documented in SECURITY.md §4).
**Number / evidence:** n/a (design decision). 1 password transmission per account lifetime; 0 passwords/API keys stored by the mod; 1 revocable token persisted.

### D-028 — Game-client backend URL (graduates P-011)
**Status:** Locked (2026-06-14, Section 4 planning)
**Choice:** The mod reads the backend base URL from its config, defaulting to `http://localhost:8000`. This matches the compose-local demo target (D-002). **Hosting the stack is a Section 7 stretch only** — no Section 4 phase depends on it.
**Why:** Confirmed reachable from inside tModLoader (spike, RUNBOOK §9). A config-driven URL makes "point at a hosted backend" a **one-line config change, not a code change** — so the default keeps the demo simple without foreclosing hosting. The hosted case is where D-027's HTTPS requirement bites; localhost does not.
**Number / evidence:** n/a (design decision). 1 config key; default `http://localhost:8000`.

### D-029 — Access+refresh token model & session revocation (Redis denylist)
**Status:** Locked (2026-06-14, Section 4 planning); **as-shipped Phase 4.1a**.
**Choice — token model:** every JWT (HS256, signed with the Vault key read from `app.state` at request time) carries `sub`=tenant_id (the RLS-context source), `role`, a unique `jti` (the denylist key), `type` (`access` | `refresh`), and `exp`. Two token types:
- **Access** — 30-min TTL (D-006). The **only** token that authorizes resource endpoints (`/bot/ask` etc.). The resource dependency rejects a non-`access` token, so a refresh token can never authorize a resource call.
- **Refresh** — 30-day TTL. Does one thing: mint a new access token at `POST /auth/refresh`. The mod persists it and exchanges it each launch (D-027). Guests get **no** refresh token (access-only; ephemeral).
- **No rotation:** `/auth/refresh` returns a new access token but **reuses** the same refresh token until expiry or logout. Plain rotation only shortens the window while forcing the mod to re-persist every launch; reuse-*detection* (the valuable variant) is deferred as **P-014**.
**Choice — revocation:** a **Redis denylist keyed by `jti`, TTL = the token's remaining lifetime** (self-expiring). `POST /auth/logout` denylists the **refresh** token's `jti` (the access token dies within its 30-min TTL on its own); an operator can force-revoke any token by denylisting its `jti`. `/auth/refresh` and the access-token dependency both check the denylist. The **`audit_log` (Postgres) records the `session.revoked` event** (D-017, SECURITY §6) so the durable trail lives there while the denylist stays ephemeral.
**Why (Redis over a Postgres session table):** Redis is **already in the stack** for short-term memory (D-010) — no new service. A `jti` → TTL entry is **light and self-expiring**: it disappears exactly when the token would have expired, so the denylist never grows unbounded and needs no GC job. The only durability we need is the audit trail, which `audit_log` already provides; a second durable table would duplicate that for no isolation benefit. This makes a token demonstrably **force-revoked**, not merely expired (CLAUDE §4.3).
**Number / evidence:** 2 token types (access 30 min / refresh 30 day); 1 Redis denylist; key = `denylist:jti:{jti}`; TTL = remaining lifetime; 0 new services. Proven in `tests/api/test_auth.py` (login pair, refresh→access, refresh rejected at resource endpoints, logout→refresh 401, denylisted access 401) — all under real Postgres + fakeredis.

**Revised 2026-06-14 (Phase 4.1a):** expanded from "session revocation via Redis denylist" to the full as-shipped **access+refresh token model**. Endpoint reconciled: the mod's saved-token exchange is `POST /auth/refresh` (D-027 folded `/client/token` in). No rotation in 4.1a (P-014 logged).

### D-030 — RLS context is transaction-local + fail-closed via NULLIF
**Status:** Locked (2026-06-14, Phase 4.1a)
**Choice:** The service layer sets the request's tenant context with `set_config('app.current_tenant_id', <tenant_id>, true)` — the **`true` third arg = `SET LOCAL`** (transaction-local). The RLS policy on `sessions`/`messages` is:
```sql
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
```
**Why transaction-local:** a per-request setting that persisted on a **pooled** connection would leak one tenant's context into the next request on the same connection — a cross-tenant breach. `SET LOCAL` reverts at transaction end, so the context can never outlive the request. The protected queries must run in the **same transaction** as the set (no intervening commit).
**Why NULLIF — the non-obvious gotcha (don't re-trip on this):** after a `SET LOCAL` reverts, the custom GUC `app.current_tenant_id` reads back as **`''` (empty string), NOT `NULL`**, on a pooled connection. The original policy cast `current_setting(...)::uuid` directly, which **raises** `invalid input syntax for type uuid: ""` on `''` — surfacing as a **500**, not a denial. And because connection pooling means *every request after the first reuses a previously-contexted connection*, that empty-string path is the **normal** case, not an edge case — any code path that queried without first setting the context would 500 instead of failing closed. `NULLIF(current_setting(...), '')::uuid` maps both the never-set (`NULL`) and reverted (`''`) cases to `NULL` → `tenant_id = NULL` → FALSE → **zero rows, no error**. True fail-closed.
**Number / evidence:** proven by `tests/services/test_rls_context.py` against the real `pgvector` Postgres connected as the **non-superuser `terramind_app`** role (a superuser bypasses RLS and would prove nothing): an uncontexted connection sees **0 rows**; a row written under tenant A's context is invisible under B's and visible under A's; a cross-tenant INSERT is rejected by the implicit WITH CHECK. Migration: `c2d3e4f5a6b7_rls_policy_nullif` (recreates the policies with NULLIF; supersedes the original `a8f3b2c1d4e5` policy comment, which wrongly claimed `NULL::uuid` fail-closed).

---

## Pending Decisions

Open questions we know we must answer. Each graduates to a `D-NNN` once settled, **with a number**.

| ID | Question | Decide during | Number it will be backed by |
|---|---|---|---|
| P-004 | Redis session TTL value | memory phase | session-length distribution / defended choice |
| P-006 | Guardrail rule set, LLM-judge prompt, and red-team set composition | guardrails phase | red-team pass rate (target: 0 successful injections) |
| P-007 | Whether to escalate to hybrid retrieval (depends on D-008) | dedicated follow-up phase after Section 3 | dense vs dense+BM25 hit@k delta (see note below) |
| P-009 | Langfuse 2.60.10 UI does not display token usage | observability polish phase | n/a (UI bug; SDK sends correct data) |
| P-010 | Per-request agent-graph compilation → cache compiled graph on `app.state` | agent polish phase | compile cost saved (~50 ms/call) |
| P-012 | Cap on total `chunks_seen` length to bound agent context cost | agent polish phase | max chunks / input-token ceiling |
| P-013 | Open nested per-iteration spans inside agent graph nodes for a tighter Langfuse trace hierarchy | observability polish phase | n/a (trace-structure polish) |
| P-014 | Refresh-token rotation + reuse detection (token-family revocation) | auth polish phase | n/a (security hardening; reuse-detection coverage) |

_P-008 graduated to D-024 (Phase 3.2): tool roster finalized at 3, MAX_ITERATIONS=5._
_P-005 graduated to D-027 (Section 4 planning): mod login-once / token-persist identity._
_P-011 graduated to D-028 (Section 4 planning): config-driven backend URL, default localhost._

**P-007 status note (Phase 2.4):** Dense-only hit@5 baseline = 0.667, below the 0.75 resolution floor (D-008). P-007 stays open. The forcing function: a dedicated follow-up phase runs the same eval harness against dense+BM25 (RRF fusion). The escalation decision rule is: **dense+BM25 must improve hit@5 by ≥ 0.05 over the dense-only baseline (i.e. hit@5 ≥ 0.717) to be adopted.** Below that delta, the added latency and complexity is not justified and dense-only stays in production. Phase 2.4 ships dense-only with the measured thresholds (D-020). The two complete misses (Q11, Q15) are caused by entity-naming gaps that BM25 also cannot fix — see EVALS.md §1.6.

**P-009 note (Langfuse token display, Phase 3.2):** The Langfuse Python SDK accepts usage data via three formats — `usage_details` dict (modern API), `usage` dict (legacy API), and `usage=ModelUsage(...)` (older API). All three were tested against Langfuse **2.60.10**; data is sent but the trace UI consistently renders "0 prompt → 0 completion (∑ 0)" on every generation event. Application code receives correct token counts from the Anthropic SDK (`AnthropicClient.chat_with_tools` returns them) — only the UI display is affected. Resolution path: upgrade Langfuse to a newer 2.x/3.x release in a future observability-polish phase. Until then, per-trace token measurement falls back to Anthropic console totals divided by call counts (the D-025 methodology).

**P-010 note (cached agent graph, Phase 3.2):** `app/services/agent.py` calls `build_agent_graph(...)` on every `/bot/ask` agent-path request. The compile cost is ~50 ms + transient memory; acceptable at project scale and demo load. Future optimization: build the graph once at lifespan and cache it on `app.state` — the retrieval pipeline, Anthropic client, and prompts are already process-singletons, so the graph closure is stable across requests. Not done in 3.2 to keep the service-layer contract simple and avoid premature optimization.

_P-011 resolved by **D-028** (Section 4 planning): config-driven backend URL, default `http://localhost:8000`; hosting is a Section 7 stretch._

**P-012 note (chunks_seen length cap, Phase 3.2):** D-025 shows agent input-token cost grows roughly linear-to-quadratic with iteration count, because accumulated tool results re-enter context on each planning call. A cap on total `chunks_seen` length (or an input-token ceiling) would bound the worst case more directly than `MAX_ITERATIONS` alone (D-024). Deferred; revisit if per-call cost exceeds the D-025 p95 (~$0.020).

**P-013 note (agent trace nesting, Phase 3.2):** The 3.2 agent graph does not open per-iteration spans (`agent.plan_iter_N`, `agent.tool_call`). Each `chat_with_tools` generation event and each `rag.retrieve` span are flat siblings under `agent.run`, so the Langfuse tree is flatter than a per-iteration hierarchy. Functional and correct for 3.2 (every call is still traced); future polish opens nested spans inside the `plan` / `execute_tools` nodes for tighter readability. Not a blocker for shipping 3.2.

**P-014 note (refresh rotation + reuse detection, Phase 4.1a):** D-029 ships **no refresh-token rotation** — the same refresh token works until expiry or logout. Plain rotation (issue a new refresh on each use, denylist the old) only shortens the leak window while forcing the mod to re-persist its token every launch; the genuinely valuable variant is **reuse detection** — if a rotated/denylisted refresh `jti` is ever presented again, revoke the whole token family (it signals theft). That adds token-family state and is deferred. The current leak bound is the 30-min access token + explicit denylist revocation, which is sufficient for 4.1a. Revisit if a stronger refresh-theft story is wanted.

---

## Revision Log

- **2026-06-03 · D-016:** Confirmed Terraria target version as 1.4.4.9 (tModLoader v2026.4.3.0). Corpus `game_version` tag locked to `1.4.4.9`. "Confirm before scraping" placeholder resolved.
- **2026-06-04 · D-007:** Locked Vault KV paths to `secret/terra-mind/anthropic` (`api_key`) and `secret/terra-mind/jwt` (`signing_key`). Logical dotted names in original decision now mapped to concrete physical paths seeded by vault-init.
- **2026-06-04 · D-017 (new):** audit_log RLS exemption and terramind_app role split locked. API connects as terramind_app (non-superuser); migrate connects as terramind (owner). audit_log has no RLS — operator-gated at the service layer.
- **2026-06-04 · D-007 (Phase 1.6 addendum):** Langfuse credentials come from env, not Vault — circular dependency and no security benefit for a dev-local stack. SDK keys seeded via `LANGFUSE_INIT_PROJECT_*` compose vars.
- **2026-06-05 · D-018 (new, graduates P-001):** Chunking strategy locked: hybrid structural + sliding-window + Cargo template synthesis. Cargo Items + Recipes scraped; NPCs and all other tables explicitly rejected. Measured (2026-06-05): 22,173 total chunks from 4,534 of 5,157 pages; 29 distinct section labels; 2,808 stats / 1,590 recipe / 170 drop / 5,962 misc / 5,278 intro chunks. Join-key gap noted: 54% of Items rows and 62% of Recipes rows have no matching wiki page (structural, not a bug — tracked in orphan_recipes.jsonl; Phase 2.4 will confirm retrieval impact).
- **2026-06-05 · D-019 (new, graduates P-002):** HNSW index, m=16, ef_construction=64, vector_cosine_ops. Recall@10 + latency numbers PENDING Phase 2.4 golden-set measurement.
- **2026-06-06 · D-019 (Phase 2.4 addendum):** Measured baseline — hit@5=0.667, hit@10=0.867, MRR@10=0.576, median 5.6 ms, p95 175.8 ms (first-call JIT warmup). Two questions (Q11 mage armor, Q15 post-Golem progression) are complete misses due to entity-naming gaps; see EVALS.md §1.6.
- **2026-06-06 · D-020 (new, graduates P-003):** RAG eval thresholds locked. hit@1_min=0.35, hit@k_min (hit@5)=0.55, mrr_at_10_min=0.45, p95_latency_ms_max=300. Derivation formula floor(b×10)/10 − 0.05 stated explicitly.
- **2026-06-06 · P-007 (Phase 2.4 update):** Dense-only hit@5=0.667 < 0.75 resolution floor. P-007 stays open. Forcing function added: dedicated hybrid phase required; escalation threshold delta ≥ 0.05 over dense-only baseline.
- **2026-06-06 · D-021 (new, Phase 2.5):** Deterministic chunk IDs via uuid5(NAMESPACE_OID, "{page_id}:{chunk_index}:{game_version}"). Root cause: prior uuid4() generated random IDs at insert, silently invalidating the golden set on volume wipe. One-time `refresh_golden_set.py` migration run; golden set now stable permanently. STEP 6 verification: down -v + rebuild produces hit@5=0.667 with unmodified eval_rag.jsonl.
- **2026-06-06 · D-022 (new, Phase 2.5):** Threshold direction convention locked: _min = floor (>=), _max = ceiling (<=), unknown suffix raises ValueError. Fixes latent harness bug where 164ms measured against 300ms ceiling was reported as a failure. Shared helper in app/core/threshold_directions.py used by both harness and refuse-to-boot check.
- **2026-06-11 · D-023 (new, Phase 3.1):** Router and FAQ model locked to claude-haiku-4-5. Live smoke test measured: router classify ~$0.00001/call, FAQ synthesis ~$0.0007/call, agent stub $0/call (no LLM). Two-request total ~$0.001. Sonnet-4-6 upgrade path reserved for Phase 3.2 agent boundary.
- **2026-06-12 · D-024 (new, Phase 3.2, graduates P-008):** Agent bounded-loop iteration cap locked at MAX_ITERATIONS=5; tool roster finalized at 3 (query_wiki, analyze_loadout, suggest_next_boss). Caveat documented explicitly: the cap bounds plan→execute cycles, NOT tool dispatches — execute_tools dispatches every tool_use block in one assistant message per +1 iteration, so Q05 did 6 query_wiki calls within ≤5 iterations. Keep 5 (1–3 iterations sufficient across all 10 eval questions).
- **2026-06-12 · D-025 (new, Phase 3.2):** Agent cost/latency profile measured over 10 hard questions (scripts/measure_agent_cost.py). Total $0.07–0.09; median ~$0.005/call, p95 ~$0.020 (Q05); median latency ~7 s, p95 ~13 s. Cost computed from Anthropic console totals (66,832 in / 4,105 out) at Haiku pricing — per-trace tokens unavailable in Langfuse UI (P-009). Input-token cost grows linear-to-quadratic with iteration count (accumulated tool results inflate context).
- **2026-06-12 · P-009/P-010/P-011/P-012/P-013 (new, Phase 3.2):** P-009 Langfuse 2.60.10 UI token-display bug (SDK sends correct data; UI shows 0/0). P-010 cache compiled agent graph on app.state (currently per-request, ~50 ms). P-011 game-client backend URL localhost vs hosted (registered from the prior informal RUNBOOK §9 reference for ID hygiene). P-012 chunks_seen length cap to bound agent context cost. P-013 open nested per-iteration spans inside agent graph nodes for a tighter Langfuse trace hierarchy.
- **2026-06-13 · D-026 (new, Phase 3.3, graduates D-009):** Hybrid class detection — Cargo `damagetype` gated on type=weapon (A2): **446 weapon rows = 198 melee + 113 ranger + 76 magic + 59 summoner → 445 distinct item_ids, ~22× the Phase 3.2 ~20-item dict** (632 rows carry a class damagetype pre-gating; 186 tools/ammo excluded by A2) + curated armor/fallback map (Cargo has 0 armor signal, A3) + LLM zero-shot fallback (~$0.0002/call, cold-start only — new spend beyond D-025's profile). item_id-primary resolution, name fallback. CI uses the curated-only DEFAULT_CLASSIFIER + synthetic Cargo fixtures (`data/raw/` gitignored, A4); production layers Cargo at lifespan (refuse-to-boot if missing / `<100` rows). D-009 fully implemented; trained classifier confirmed not needed. 8 analyze_loadout + 9 suggest_next_boss fixtures unchanged.
- **2026-06-14 · D-027 (new, Section 4 planning, graduates P-005):** Game-client identity = mod login-once / token-persist. Username+password once → `/auth/jwt/login` → password discarded → token saved in mod config → exchanged at `/client/token` each launch for a short-lived JWT (RLS-context source). Registration is portal-only; logout deletes + denylists the token (D-029). Mod never stores a password or API key — only a revocable token. HTTPS required for the one password transmission in any hosted setup; localhost default (D-028) is in-machine.
- **2026-06-14 · D-028 (new, Section 4 planning, graduates P-011):** Game-client backend URL is config-driven, default `http://localhost:8000` (compose-local, D-002). Hosting is a Section 7 stretch; no Section 4 phase depends on it. Config-driven → "hosted" is a one-line change, not a code change.
- **2026-06-14 · D-029 (new, Section 4 planning):** Session revocation via Redis denylist keyed by `jti` with TTL = token remaining lifetime. Logout/operator-revoke denylists the `jti`; `/client/token` + authed endpoints check it; `audit_log` records the event (durable trail). Redis chosen over a Postgres session table — already in the stack (D-010), self-expiring, no GC job, no new service. Enables demonstrable force-revoke, not just expiry (CLAUDE §4.3).
- **2026-06-14 · D-006 (Phase 4.1a graduation):** JWT TTLs locked — access 30 min, refresh 30 days, server-pinned (not user-configurable). Access bounds leak-damage; refresh = stay-logged-in-a-month, revocable via denylist.
- **2026-06-14 · D-029 (Phase 4.1a, revised in place):** Expanded to the as-shipped access+refresh token model (claims sub/role/jti/type/exp; access authorizes resources, refresh only mints access at `/auth/refresh`; guests access-only). **No rotation** (P-014). `/client/token` folded into `/auth/refresh` (D-027). Proven in tests/api/test_auth.py under real Postgres + fakeredis.
- **2026-06-14 · D-030 (new, Phase 4.1a):** RLS context is transaction-local (`set_config(..., true)` = SET LOCAL) and fail-closed via `NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`. The non-obvious gotcha: after SET LOCAL reverts on a pooled connection the GUC is `''` (not NULL), so the original `::uuid` cast threw a 500 on every uncontexted query (the normal pooled-reuse case, not an edge case) — NULLIF maps `''`→NULL→deny, no error. Proven by test_rls_context.py as non-superuser terramind_app. Migration c2d3e4f5a6b7_rls_policy_nullif.
- **2026-06-14 · P-014 (new, Phase 4.1a):** Refresh-token rotation + reuse detection (token-family revocation) deferred — plain rotation is low value; reuse-detection adds family state. Current bound = 30-min access + denylist revocation.