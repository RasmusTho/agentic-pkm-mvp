# Roadmap — Strategic Control

## Version Ladder Overview
| Version | Intent | State |
| --- | --- | --- |
| v4.3 | Establish the PER ingest loop, Outbox wiring, and CI contracts. | Delivered |
| v4.4 | Harden observability, Store abstraction, and identity plus conflict handling. | Delivered |
| v4.5A | Stabilize unified ingestion, enforce deterministic memory-first CI, and document promotion rules. | Delivered |
| v4.5B | Fitness guards + ingestion polish, rerank + chunk dedup readiness. | Delivered |
| v4.6 | Retrieval quality upgrades (cross-encoder, diarization adapter, RelationIndex fitness, golden eval). | Active (Objectives A–D) |
| v4.6-B | Relation coverage lift (deterministic extraction + audit trail). | Delivered |
| v4.6-C | Diarization-aware chunking & metrics. | Active |
| v4.6-D | CI gates + summary hardening. | Delivered (2025-02-18) |
| v4.7 | Reasoning layer & reflexive agents over the knowledge graph. | Active (Objective A) |
| v4.8 | Agent coordination layer (A2A envelopes + choreography). | Planned |
| v4.9 | MCP integration + LLM-driven planning. | Planned |

## Current Stable Baseline (v4.5A)
v4.5A is the deployable baseline: Normalizer→PromotionAgent path is verified end-to-end, promotion cooldowns are enforced, and CI is green when `pytest -q -m "not pg"` passes using `STORE_BACKEND=memory` and mock LLMs. Architectural invariants to preserve: Core-6 frontmatter is immutable once normalized, Outbox events remain append-only, PromotionAgent decisions are idempotent, and audit logs stay deterministic JSONL. Any change that violates these invariants or introduces non-deterministic mocks must be postponed to v4.5B+.

## Delivered: v4.5B Fitness & Hook Readiness
- Unified chunking + dedup pipeline via `app.ingest.chunk_policy` and `app.ingest.deduper`, surfaced through `app.agents.pipeline.ingest_and_chunk()`.
- Rerank hook integrated after hybrid search with provider matrix and `hook_adapter`.
- CI fitness guards: `app.fitness.metrics.qas003_hybrid_latency()` and `qas010_outbox_to_index_latency()` enforce QAS-003 and QAS-010 thresholds; GitHub smoke workflow prints their JSON reports.
- Documentation aligned (Architecture/Roadmap/Status) and status board lists P1 (rerank) + P2 (chunk/dedup) as delivered.

### Fitness Functions Enforced in CI
| Fitness ID | Target | Enforcement |
| --- | --- | --- |
| QAS-003 Hybrid Search Latency | p95 < 250 ms (memory mode) | `python -m app.fitness.report` — fails CI if threshold exceeded. |
| QAS-010 Outbox → Index Latency | ≤ 2 s from event emission to indexing | Same report; synthetic ingest events pumped into `MemoryVectorIndex`. |
Both checks run with `STORE_BACKEND=memory` and `LLM_PROVIDER=mock` so CI stays deterministic.

## Active Work (v4.6)
### Objective A — Cross-Encoder Rerank Provider *(delivered — SoT v4.6-A)*
Acceptance criteria (kept active in CI):
- Golden corpus contains 12–20 queries, each with 8–15 candidates and 2–3 relevant docs, stored deterministically under `data/golden/*`.
- `ce_local` heuristic lowercases + strips punctuation, applies capped term-frequency boosts with IDF-like weighting, adds exact n-gram bonuses, and breaks ties via the original candidate score; runtime stays O(n·|query|) and CI remains offline.
- Provider selection routes to `ce_local` only when `RERANK_ENABLE=1` and `RERANK_PROVIDER=ce_local`, flags-off runs preserve baseline ordering, and `ce_http` never triggers network calls inside CI.
- Evaluation runs baseline vs ce_local, prints all four CI summary lines (latency, eval, eval delta, relation coverage), and fails when ΔnDCG@10 < +0.01 **and** ΔP@10 < +0.005 while rerank flags are enabled.

Status: ce_local heuristics and tie-breakers ship as part of SoT v4.6-A, the golden set now spans 16 queries × 10 candidates, tests cover deterministic scoring + provider selection, and `python -m app.fitness.report` currently records ΔnDCG@10 = +0.070 with DP10 = +0.000; defaults remain inert with flags off.

### Objective B — Relation Index v1 + Orphan Gate *(delivered)*
Implement in-memory RelationIndex CRUD + `has_any()`, propagate provenance links, and gate promotions with the orphan guard (`PROMOTION_ALLOW_ORPHANS` + `PROMOTION_ORPHAN_OVERRIDE_REASON`). Status: gate enforced by default, overrides audited, and CI reports relation coverage from the golden sample. Acceptance: relation coverage metrics and tagging readiness require ≥95% promoted objects linked.

### Objective B2 — Relation Coverage Lift *(delivered — SoT v4.6-B)*
- Deterministic extraction (frontmatter keys, tag prefixes, “See also” headings) populates `supports|extends|contradicts|derived_from` links via `prepare_relations_for_promotion()`; coverage + validity both sit at 100 % on the golden sample.
- Audit trail: every relation write emits `relation.added`, missing or invalid targets emit `relation.missing`, and `PROMOTION_REQUIRE_RELATIONS=1` (staging) blocks promotions without inferred links; overrides remain audited via `PROMOTION_ORPHAN_OVERRIDE_REASON`.
- CI now prints the fifth summary line `CI SUMMARY RELATIONS coverage=100.00% validity=100.00% target=95%` and fails if coverage drops below 95 %; execution stays offline (`STORE_BACKEND=memory`, `LLM_PROVIDER=mock`).

### Objective C1 — Diarization-aware Chunking *(active — SoT v4.6-C)*
- `speaker_aware_chunks()` aligns spans with diarization segments (`speaker,start,end`) so transcripts remain coherent per speaker without exceeding the character budget.
- Pipeline + indexing propagate `speaker` metadata (and `speaker_count` in `text.chunk.created` audits) whenever `DIARIZE_ENABLE=1`; flag-off path is byte-for-byte identical to the legacy chunker.
- Fitness adds chunk-length p95 and speaker-count metrics with a sixth CI summary line `CI SUMMARY DIARIZATION chunk_p95=<val> speaker_avg=<val> flag=on`, failing if the diarized p95 exceeds the baseline by >5 %.

### Objective D1 — CI Gates & Baselines *(delivered — SoT v4.6-D)*
- Baselines for QAS003/QAS010, eval, relation coverage/validity, and diarization chunk lengths are versioned in `ops/quality/baselines.yaml` with optional overrides via `THRESHOLDS_PATH`; `GATE_STRICT=1` tightens delta expectations (+0.01 nDCG or +0.005 precision).
- `app.fitness.report` parses the six CI summary lines it emits, enforces thresholds (latency ≤ baseline × tolerance, rerank deltas ≥ configured mins, relation coverage/validity ≥95 %, diarization p95 ratio ≤0.95), prints `CI SUMMARY GATES ok=<bool> reasons=<codes>`, and exits non-zero on regression.
- `.github/workflows/ci-smoke.yaml` tees the report into `tmp/ci_summary.log` and fails immediately if any of the seven lines are missing or if `ok=false`, ensuring every PR presents the hardened CI contract without leaving offline mode.

### Objective C — Diarization Hook *(active)*
`DIARIZE_ENABLE` toggles segmentation; providers include `none`, `mock`, and `external` (HTTP). Metadata preserves `{speaker, text}` entries so ingestion/promotion retain conversation context. Acceptance: mock provider yields ≥2 segments, disabled path is unchanged, no CI dependency on external ASR, and chunk policy respects speaker segments.

### Objective D — Golden Set + Evaluation Metrics *(active)*
Ship synthetic corpus (`data/golden/*`), compute Precision@k and nDCG@k, and assert rerank quality never drops below baseline. Evaluation runs inside the not-pg suite, CI summary prints `EVAL P@10` and `nDCG@10`, and failures block merges.
SoT v4.6-A expands the corpus to 16 deterministic queries (10 candidates each) and ties CI failure conditions directly to ΔP@10 / ΔnDCG@10 thresholds so regressions remain visible without changing defaults.

### Operational Acceptance
- Latency guard: ingest→index p95 remains ≤ 2 s while hooks and dedup are enabled.
- Promotion safety: PromotionAgent cooldown metrics show <2% replays per day and orphan gate coverage ≥95%.
- Documentation + CHANGELOG updated whenever code changes land.

## Forward Outlook (v4.7)
### Objective A — LLM Reasoning Layer v1 *(active — SoT v4.7-A)*
- `REASONING_ENABLE=1` routes notes + relation snapshots through `get_reasoner()` (mock in CI, Ollama locally) using strict prompts; outputs must pass schema validation (`claims`, `evidence`, `inferences`) before being stored/audited.
- Fitness adds an eighth summary line `CI SUMMARY REASONING claims_avg=<v> inferences_avg=<v> conflicts=<n> flag=on` with baselines defined in `ops/quality/baselines.yaml`; gates require non-zero inferences_avg and conflicts ≤ baseline when the flag is on.
- Docs + README describe baselines and overrides (`THRESHOLDS_PATH`, `GATE_STRICT=1`), ensuring PRs paste the seven existing lines plus the new REASONING line.

## v4.8 — Agent Coordination (A2A)
### Goals
- Introduce A2A envelopes and message choreography so agents communicate via audited events.
- Allow agents to request, respond, and critique peer work without bypassing Stores/Outbox.
- Enable deterministic multi-agent task sequences (e.g., Classifier → Reasoner → Projector) with replayable traces.
- Provide orchestration hooks plus a sample chain template that operators can rehearse locally.

### Acceptance Criteria
- `agent.request.created`, `agent.response.created`, and `agent.critique.created` documented under Event Choreography.
- Base agent exposes `handle_agent_message()` and routes envelopes via A2A middleware.
- ≥1 multi-agent interaction scenario scripted end-to-end (Classifier requests Reasoner, Reasoner responds, Projector critiques).
- CI ships deterministic A2A fixtures; default flags keep the feature inert (no new smoke gates) until `A2A_ENABLE=1`.

## v4.9 — MCP Integration + LLM Planning
### Goals
- Ship an MCP server that exposes ingest, retrieval, relation, and promotion tooling directly from PKM.
- Embed an MCP-aware client into the agent Act phase so planners/agents can call tools during execution.
- Introduce an LLM Planner that outputs structured agent plans based on Reasoning Layer inputs.
- Planner leverages Reasoning Layer v1 plus A2A envelopes, and can either call MCP tools or emit additional A2A requests.

### Acceptance Criteria
- MCP server exposes ≥5 stable tools (`pipe_note`, `search_notes`, `get_claims`, etc.) with documentation.
- MCP client sits behind a `ToolProvider` abstraction used inside agents and planners.
- Planner v1 covered by deterministic mock tests; CI stays green using the mock planner backend.
- Reasoning + planning flows remain deterministic in CI (mock planner) while docs + event schema outline MCP + planner wiring.

## Cross-Cutting Initiative — v4.9.x
### Goal
- Align A2A, MCP, and Planner so they form a unified multi-agent execution model while preserving backward compatibility with CLI-only workflows; older scripts continue to function with all new flags disabled.

## Forward Outlook (v5.x)
Symbolic reasoning layer adds RDF/OWL/SHACL validation before promotion. Knowledge graph services expose RelationIndex externally for governance queries. Logic gates allow Reviewer/PromotionAgent to assert multi-object policies. Reflexive agents learn from audit feedback to auto-tune PER plans without skipping human checkpoints.

## Governance & CI Contract
- Green means: `pytest -q -m "not pg"` passes, docs lint (markdownlint + vale) is clean, `docs/DIAGRAMS.md` exports without mermaid errors, and audit replay tests remain deterministic.
- Maturity states: inbox → processed → promoted → evergreen. Inbox objects may be dropped, processed objects must retain Core-6, promoted objects require Reviewer approval, and evergreen objects are eligible for publication + search.
- Update ritual: after each increment, Codex opens a PR that regenerates STATUS (CI snapshot + blockers), refreshes ROADMAP acceptance criteria, and cross-links ARCHITECTURE when new agents or stores appear. No increment closes until these docs reflect reality.
## Vault-as-GUI Settings Architecture

### Goal
Göra hela systemets konfiguration mänskligt redigerbar i vaulten (Markdown) och maskinellt säker via en typad kompilator som genererar kanoniska runtime-artefakter (YAML/JSON). Vaulten är kontrollpanelen; koden läser endast kompilerade artefakter.

### Scope (MVP)
- @Settings/ i vaulten med globala filer + agentfiler.
- Parser för Markdown-sektioner: checkrutor, key/value-tabeller, samt auktoritativa ```yaml settings-block.
- Pydantic-validering mot modellschema.
- Sekretshantering via `${SECRET:NAME}` med upplösning från `.env` eller SOPS.
- Kompilering till `runtime/settings/**` och event `settings.changed`.
- CLI: `python -m app.cli settings compile` och `settings watch`.
- Hot-reload-hake i appen.

### Out of scope (v4.7+)
- Full UI-reflektion av “compiled values” i Obsidian.
- Profilbyten per miljö via feature flags.
- Avancerad policy för farliga ändringar.

### Deliverables
- `vault/@Settings/*` med exempel och README.
- `app/settings/{loader,parsers,models,compiler,hotreload}.py`
- `app/cli.py` kommandon `settings compile|watch|validate`.
- CI-steg: schema-check + determinism på kompilering.
- Dokumentation i `docs/ARCHITECTURE.md` och uppdaterad `docs/STATUS.md`.

### Fitness & Acceptance
- F1: Kompilering av hela @Settings ≤ 500 ms i dev.
- F2: 100% schema-valideringscoverage för Global + minst 4 agenters settings.
- F3: Determinism i artefakter.
- F4: Hot-reload inom ≤ 2 s.
- F5: Sekretläckage = 0 i `runtime/`.

### Milstolpar
- M1: Struktur & modeller.
- M2: CLI compile + watch + events.
- M3: CI-gate.
- M4: Utökning till alla agenter + sekretpolicy.
