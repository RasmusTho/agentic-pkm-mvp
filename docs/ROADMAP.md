State: SoT v4.10 Reality-MVP (current core).
# Roadmap — Strategic Control

## Reality-MVP (Current focus — SoT v4.10)
- Deliver a reliable single-user Reality-MVP: stable ingestion of the real Obsidian vault, minimal external ingest, ASK API, observability backend, and an interim GUI for status + ASK.
- Zones overlay (Active/Warm/Cold) runs as a derived projection across Stores; orthogonal to lifecycle (inbox → processed → evergreen → archived) and temporal value (ephemeral/normal/evergreen).
- Two planes: vault (human graph with minimal frontmatter) and external corpus (newsletters/emails/PDFs) that are indexed and retrievable but not shown as Obsidian notes.
- Human frontmatter stays lightweight; system metadata (signals, usage, relations, promotions, zone inference) lives in SetDB/AMG + Stores. Core-6 remains a projection.
- Collaboration and multi-user flows are explicitly deferred until after the Reality-MVP is solid.

### Remaining Reality-MVP (v4.10) work
- Harden vault ingestion on the real vault (resume/error handling now recorded in summaries; malformed frontmatter handled gracefully) and finalize external drop-folder ingest into `external_raw` (txt/md path delivered; extend to real newsletter/PDF samples).
- Polish ASK API responses (sources + zone/plane tags + latency surfaced) and wire observability backend + CLI (object counts per plane, ingest timestamps/errors, ASK latency/error metrics).
- Build the interim GUI (status + ASK surface) and advance Orchestrator runtime beyond the skeleton (LangGraph + real MCP/agent execution with dual CLI/Orchestrator toggles).

### Reality-MVP scope
1) **Vault ingestion** — CLI/agent command to ingest selected vault folders into ObjectStore with Core-6 fields and provenance; emit Outbox events and index into VectorIndex.
2) **External corpus (minimal)** — ingest a small, real set of external documents (e.g., exported newsletters/PDFs) into `external_raw` objects; store + index them without exposing them as vault notes (txt/md drop-folder path implemented).
3) **ASK API** — FastAPI endpoint that answers questions with sources `{uuid, title, origin (vault/external), zone if known, path/source_ref}` and latency.
4) **Observability backend** — status service + CLI that surfaces per-store object counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency.
5) **Interim GUI** — simple FastAPI-served page showing system status and an ASK box with visible sources; explicitly a temporary observability/interaction surface.

## Version Ladder Overview
| Version | Intent | State |
| --- | --- | --- |
| Reality-MVP (SoT v4.10) | Vault ingestion + external corpus plane + ASK API + observability + interim GUI | Active (current focus) |
| v4.3 | Establish the PER ingest loop, Outbox wiring, and CI contracts. | Delivered |
| v4.4 | Harden observability, Store abstraction, and identity plus conflict handling. | Delivered |
| v4.5A | Stabilize unified ingestion, enforce deterministic memory-first CI, and document promotion rules. | Delivered |
| v4.5B | Fitness guards + ingestion polish, rerank + chunk dedup readiness. | Delivered |
| v4.6 | Retrieval quality upgrades (cross-encoder, diarization adapter, RelationIndex fitness, golden eval). | Historical foundation (Objectives A–D maintained) |
| v4.6-B | Relation coverage lift (deterministic extraction + audit trail). | Delivered |
| v4.6-C | Diarization-aware chunking & metrics. | Delivered (flagged feature) |
| v4.6-D | CI gates + summary hardening. | Delivered (2025-02-18) |
| v4.7 | Reasoning layer & reflexive agents over the knowledge graph. | Deferred until after Reality-MVP (flag-gated/mocks only in CI) |
| v4.8 | Agent Coordination (A2A Protocol V1 + Orchestrator messaging hooks). | Planned (post-MVP) |
| v4.9 | MCP Integration V1 + Planner Agent (LLM) plan schema. | Delivered (planning schema + descriptors; transport mocked) |
| v4.10 | Orchestrator Runtime V1 (LangGraph execution of Planner Agent output). | Delivered skeleton; further LangGraph/MCP execution planned alongside Reality-MVP |

Current Reality-MVP work supersedes the statuses of the older tracks above; rows remain for SoT history.

## Priority Bands
- **Short-term (Reality-MVP)** — finish vault ingestion (real vault folders), minimal external ingest (`external_raw` pipeline), ASK API with sources + latency, observability backend (object counts, ingest runs, ASK usage), and interim GUI surface. Zones and planes are enforced as overlays without requiring folder moves; collaboration deferred.
- **Medium-term** — Reflection layer (weekly review support with zone coverage and idea-level histories/diffs); Serendipity (exploration modes that surface Cold/older but relevant items using zone + temporal signals); Synthesis/communication pipeline (turn fragments into slides/reports/posts with traceable provenance and citations); Lifelong learning layer (goals, progression, spaced recall tied to learning objectives and note relations).
- **Long-term** — Collaboration and collective intelligence (multi-user vaults/sets/spaces, shared promotion flows, team-level knowledge graphs) after single-user Reality-MVP and reflective layers are stable.

## v5.x outlook (post-4.x)
- Master/satellite sync protocol (Git/iCloud over Markdown + VaultMirror; see `docs/PROTOCOL_SATELLITE_SYNC.md`), targeting a single human across multiple runtimes.
- PanelAgent follow-ons (v5.0 step 2+) that fan out `panel.intent.created` into actionable flows and integrate with Planner/Orchestrator; AI panel UX remains per `docs/examples/ai-panel-example.md`.
- Expansion of Yggdrasil modules beyond Mimer/Hugin/Ratatosk: Munin (media), Brokkr (project workshops), Tyr (formal records), and fuller Heimdall stack, keeping Mimer as the semantic hub (see `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`).

## Current Stable Baseline (v4.5A)
v4.5A is the deployable baseline: Normalizer→PromotionAgent path is verified end-to-end, promotion cooldowns are enforced, and CI is green when `pytest -q -m "not pg"` passes using `STORE_BACKEND=memory` and mock LLMs. Architectural invariants to preserve: Core-6 frontmatter is immutable once normalized, Outbox events remain append-only, PromotionAgent decisions are idempotent, and audit logs stay deterministic JSONL. Any change that violates these invariants or introduces non-deterministic mocks must be postponed to v4.5B+. The historical sections below (v4.5B–v4.10) remain for context while Reality-MVP sequencing above defines the active work.

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
- `REASONING_ENABLE=1` routes notes + relation snapshots through `get_deliberation_agent()` (mock i CI, Ollama lokalt) using strict prompts; outputs must pass schema validation (`claims`, `evidence`, `inferences`) before being stored/audited.
- Fitness adds an eighth summary line `CI SUMMARY REASONING claims_avg=<v> inferences_avg=<v> conflicts=<n> flag=on` with baselines defined in `ops/quality/baselines.yaml`; gates require non-zero inferences_avg and conflicts ≤ baseline when the flag is on.
- Docs + README describe baselines and overrides (`THRESHOLDS_PATH`, `GATE_STRICT=1`), ensuring PRs paste the seven existing lines plus the new REASONING line.

## v4.8 — Agent Coordination (A2A)
### Goals
- Introduce the canonical A2A envelope schema (`agent.request.created`, `agent.response.created`, `agent.error`) and thread it through the Orchestrator so multi-agent work stays audited.
- Allow agents to request, respond, and critique peer work without bypassing Stores/Outbox, keeping Planner Agent outputs replayable.
- Enable deterministic multi-agent task sequences (e.g., Classifier → DeliberationAgent → Projector) with Orchestrator-managed routing.
- Provide orchestration hooks plus a sample chain template (Classifier → DeliberationAgent → Projector) that operators can rehearse locally.

### Acceptance Criteria
- `agent.request.created`, `agent.response.created`, and `agent.error` documented under Event Choreography with Core-6 + trace requirements.
- Base agent exposes `handle_agent_message()` and routes envelopes via A2A middleware managed by the Orchestrator.
- ≥1 multi-agent interaction scenario scripted end-to-end (Classifier requests DeliberationAgent, DeliberationAgent responds, Projector critiques) with deterministic fixtures.
- CI ships mock-backed A2A fixtures; default flags keep the feature inert (no new smoke gates) until `A2A_ENABLE=1`.

### Delivered so far
- Canonical A2A message schema + audit events (`agent.request/response/error`) implemented with deterministic mocks; routing/orchestrator playback remains on the roadmap.

## v4.9 — MCP Integration + LLM Planning *(Delivered — SoT v4.9)*
### Delivered Scope
- Structured `Plan`/`PlanStep` schema finalized with dependency validation and JSON-serializable metadata shared by all planner backends.
- Deterministic `MockPlanner` + Ollama-backed `LLMPlanner` providers, with automatic fallback/audit logging when `PLANNER_PROVIDER=llm` is misconfigured under mock LLMs.
- Static MCP descriptor registry augmented with `allowed_args` + `mock_result`, keeping MCP references deterministic in CI and giving the Orchestrator enough metadata to validate tool calls safely.
- Pipeline hook (`app.agents.pipeline.maybe_plan_for_object`) emits `planner.plan.created` and feeds plans to the Orchestrator when both planner/orchestrator flags are toggled.

### Remaining MCP Work
The in-process MCP server/client and LangGraph-native orchestration continue under v4.10. Mocks cover all descriptors already, so once the transport is ready the executor can swap from stubbed to real calls without altering Planner outputs.

## Cross-Cutting Initiative — v4.9.x
### Goal
- Align A2A, MCP, and Planner so they form a unified multi-agent execution model while preserving backward compatibility with CLI-only workflows; older scripts continue to function with all new flags disabled.

## v4.10 — Orchestrator Runtime *(Active — Skeleton delivered)*
### Delivered so far
- `app/orchestrator/` runtime + executor that validate plan structure, emit `orchestrator.step.*`, replay agent/tool steps deterministically, and keep MCP/A2A calls mocked in CI.
- MCP stub execution now enforces descriptor `allowed_args`, returns descriptor `mock_result`, and logs `mcp.tool.call.started|finished`.
- Agent calls route through `send_agent_request` + the default Agent handler, producing `agent.request.created` and default `agent.error.created` (`error_type=not_implemented`) so the control plane stays audited end-to-end.
- Pipeline hook `maybe_execute_plan()` gated on `ORCHESTRATOR_ENABLE` runs immediately after planning, keeping CLI ingest backward compatible when the flag is off.

### Next Milestones
- Replace the mock executor with an MCP-connected ToolProvider plus LangGraph scheduling primitives for branching + retries.
- Add richer status reporting (plan aggregates, step retries) and CLI toggles that let operators dual-run CLI + Orchestrator before promoting the new runtime to default.
- Continue keeping CI deterministic: new integration tests must rely on mocks and the eight-line summary contract.

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
