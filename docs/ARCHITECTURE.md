State: SoT v5.5 Reality-MVP baseline locked (watcher safety, panel action provenance, and concurrency hardening) with the forward line now entering v5.6 LangGraph/Reasoning rollouts.
Doc role: Core SoT
Authority: Active runtime architecture source of truth for the current baseline and runtime contracts; wins over roadmap and historical references on current-state questions.
# Architecture — SoT v5.5 Reality-MVP baseline (forward line v5.6)

This document is the active architecture source of truth for the SoT v5.5 Reality-MVP baseline and the place where current runtime contracts are defined.

Historic SoT snapshots and older plans live in `docs/archive/`; the 4.x ladder history is in `docs/history/SOT_4X_HISTORY.md`. Forward-looking plan lives in `docs/ROADMAP.md`.
Those documents are kept for reference but are not active truth for the current baseline. If a historical or roadmap document conflicts with this document on current-state runtime architecture, this document wins.

This architecture focuses on the runtime and data model for the Mimer module (the Obsidian vault + ingestion/indexing/agents) within the broader Yggdrasil system.

Related documents and authority boundaries:
- `docs/HUMAN-FLOWS.md` is the user-facing behavior contract. Any architecture change that alters user-visible behavior should be validated against it before shipping.
- `docs/SYSTEM_DESIGN_v4.10.md` is a historical reference for external dependencies, deployment topology, and human-facing surfaces from the v4.10 foundation snapshot. It is useful background, but it is not authoritative for the current v5.5 baseline.
- `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md` is a historical high-level module map retained for orientation and naming continuity. It may not reflect current v5.5 wiring and should not be treated as the active system map when evaluating current behavior.

## Fitness Functions

Fitness functions capture the high-level criteria that must hold true for the runtime to be considered healthy (indexing uptime, worker heartbeats, doc guardrails, etc.). These functions are expressed as CI jobs, operational checklists, and runtime invariants that are enforced before code merges or releases.

### Instance model (internal master/satellite plumbing)
- SettingsBundle includes `instance` with `id` (e.g., `home`, `work`, `laptop`) and `role` (`master` or `satellite`).
- Default when nothing is configured: `id="home"` and `role="master"`, matching the Reality-MVP single-runtime focus.
- Scope: internal plumbing that informs events/logs and future sync topology; no change to the Obsidian surface or frontmatter.

## Contracts (concept anchors)

Architecture describes how things are wired today; these documents define what must remain stable as implementations evolve:

- `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md`
- `docs/PROJECT_KERNEL.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`

Connector/Watcher/Inbox decisions (architecture alternatives, watcher matrix, inbox taxonomy, contract tweaks, and guardrails) live in `docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md`, giving you the detailed connector nomenclature that aligns with the summaries above.

## Component Catalog
- See `docs/COMPONENTS.md` for the canonical, human- and machine-readable list of active components (stores, agents, embeddings, rerankers, eval stack, observability). Update it when wiring new component entrypoints under `app/components/*`.
- The outbox/event system uses a common envelope (`event`, `trace_id`, `source`, `timestamp`, `payload`, `meta`) defined in `app/events/schema.py` and enforced by architecture tests; emitters should write via outbox helpers to preserve the contract.

## Boundary Map (Current)
- Current architecture boundary map (Mermaid source): `docs/diagrams/architecture.mmd`.
- Terminology in the map:
  - `Omgivning (utanför systemgräns)` = actors/services outside this system.
  - `Systemlandskap / driftsberoenden (ej i kodbasen)` = runtime dependencies owned by the system but not part of this repository (for example Postgres, Obsidian, vault filesystem).
  - `Koddomän (denna kodbas)` = components implemented in this repository.
- The map also marks:
  - Internal interface abstractions (`VaultPort`, `KnowledgePort`, store protocols).
  - Representative internal functions used as runtime seams between modules.

## SoT lines
- **SoT v5.5 Reality-MVP baseline (locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guardrails on top of the stable vault ingest, hybrid retrieval/ASK, observability/status surfaces, and orchestrator runtime V1.
- **SoT v4.10 Reality-MVP (foundation snapshot)** — single-user PKM with stable vault ingest, minimal external ingest, hybrid retrieval + ASK with sources/latency, observability/status surfaces (CLI/API/GUI), and orchestrator runtime V1. Retained as the foundation history; superseded by the v5.5 baseline.
- **SoT v5.x Agentic PKM (active forward line, currently entering v5.6)** — Agentic flows (PanelAgent v5+), Satellite Sync (`docs/PROTOCOL_SATELLITE_SYNC.md`), and Yggdrasil modules (Munin/Brokkr/Tyr/Heimdall) that extend the v5.5 baseline; richer orchestration (LangGraph + MCP ToolProvider) and reasoning live here. The forward line includes the watcher/agent infra track: v5.1 watcher-ready ingest/panel flows (including targeted ingest via `ingest-vault-paths` and multi-note panel CLI), v5.2 snapshot-based CLI polling watcher MVP (`vault-watcher-run` driving ingest + panel), v5.3 explicit policy for auto-panel via frontmatter gating watcher runs, v5.4 watcher hardening/ergonomics (dry-run, max-notes guard, structured summaries), and v5.5 planner pipeline + CLI-first orchestration.

### Runtime watcher choice
- Registry watcher is the runtime default; start-system flows and Docker compose use `python -m app.cli watcher run` with `configs/watchers.yaml`.
- Settings tiering enforcement: watcher dev/lab tuning env vars are ignored in normal runtime (`PKM_SETTINGS_PROFILE=operator`) and require explicit `PKM_SETTINGS_PROFILE=lab`.
- Legacy snapshot watchers (`vault-watcher-run`, `vault-watcher-daemon`, runtime-loop) are dev-only, require `PKM_SETTINGS_PROFILE=lab`, and are not used in runtime start-system flows.
- Store object table is canonicalized to `store_objects`; legacy `objects` rows are best-effort backfilled when `store_objects` is empty so runtime reads/writes stay on one table.
- Legacy `scripts/fs_watcher.py` note lifecycle operations route through `VaultPort` (`FilesystemVaultAdapter`) rather than direct sink/pass-through writes.
- DB outbox is canonical in runtime; JSONL outbox is audit/diagnostic only.

### Architecture Statement: Multi-agent outer, LangGraph inner
- Outer architecture: many autonomous agents coordinate via events/A2A envelopes; the Orchestrator routes/executes plans but does not embed each agent’s internal reasoning or decision logic.
- Inner architecture: each agent is modeled as a LangGraph-driven state machine with an explicit `AgentState`; non-trivial decisions (what to do, in what order) belong inside these graphs rather than outer pipelines.
- Tools/MCP: tools are actions an agent chooses from within its LangGraph; they should not be hard-wired at the pipeline/Orchestrator level beyond routing envelopes.
- Examples: the ASK agent already follows this pattern (`app/agents/ask/graph.py` + `AgentState`); PanelAgent is partially aligned today (Runtime V1 fixed mapping) with a planned migration to the same LangGraph + AgentState pattern (PanelAgent 2.0).
- Current adoption is phased: ASK and PanelAgent use LangGraph; most other agents remain deterministic pipelines until v5.6 rollout phases.

## Agent Implementation Pattern (Normative)
- Agents MUST route reasoning/tool calls through the ReasoningFacade once it is available.
- LangGraph agents SHOULD share a common BaseLangGraphAgent to keep state transitions and tool invocation uniform.
- Agents MUST preserve external event contracts and Outbox envelopes during migrations.
- Implementation details will live in `docs/AGENT_IMPLEMENTATION.md` (placeholder for later).

Tests: `tests/architecture/test_architecture_tests_validation.py::test_import_boundary_tests_dont_allow_escape_hatches`

## Concurrency & Idempotency
- DedupTaskQueue keeps watcher auto-run tasks keyed by note+hash, feeding the `skipped_dedup` telemetry and preventing duplicate panel executions.
- Event idempotency plus an EventDedupStore in the promotion consumer ensure `promote.intent.created` replays are no-ops; consumers still emit diagnostics when skipping duplicates.
- Optimistic write guard and `DEFAULT_WRITE_GUARD` combined with the per-note opt-out (`ai_panel_auto_run: never` / `ai_panel.auto_run: never`) keep note updates deterministic and fail safe on version mismatches.
- See `docs/CONCURRENCY.md`, `docs/EVENTS.md`, and `app/promotion/consumer.py` for the enacted guardrails and testing strategy.

## Boundary Enforcement
- Domain-scoped retrieval defaults to excluding cross-domain results; set `ASK_DOMAIN_SCOPE` to the active domain and use `bridge_domains` for explicit inclusion.
- Panel/UI sections are a control surface and MUST NOT be indexed as knowledge.
- When writes are blocked (WriteGuard / `safe_mode`), reviewed notes MUST NOT be mutated without explicit intent/APPLY.

## Reality-MVP Orientation
- Primary focus: make ingestion of the real Obsidian vault stable, add a minimal external ingest path, expose a reliable ASK API, and ship observability plus an interim GUI so the system is usable end to end.
- Zoned cognition overlay (Active/ Warm/ Cold) applied on top of the knowledge base; zones are derived from signals (usage, recency, trust) rather than folder names.
- Two planes: Obsidian vault as the human graph (LYT + PARA) with minimal human frontmatter, and an external corpus plane (newsletters/emails/PDFs) that is indexed and retrievable but never rendered as Obsidian notes.
- Metadata backbone lives in Stores + SetDB/AMG: Core-6 frontmatter remains a projection for humans (see `docs/CORE_CONTRACT.md`), while system metadata (signals, relations, usage counts, agent reflections) sits in the data layer.
- Collaboration/multi-user stays out of scope for Reality-MVP; the current work is single-user, vault-first reliability.

## Zoned Cognition Overlay
- Active (Hot): the few items currently competing for conscious attention; small, rotating set.
- Semi-Active (Warm): ongoing projects/areas referenced regularly but not hourly.
- Peripheral (Cold): long-term or background material that should stay searchable without cluttering the surface; Cold can still contain evergreen, high-value notes.
- Zones are orthogonal to lifecycle (inbox → processed/staging → evergreen → archived) and to temporal value (ephemeral vs normal vs evergreen longevity). A note can be evergreen and Cold, or ephemeral and Active.
- Zones are derived overlays driven by system metadata (recency, relations, usage), not mandatory folder/tag names; they can be projected into ASK responses and GUI status but do not dictate file layout.

## Core Contract, State Axes, and Overlays (vNext)
- Core contract: Core-6 is the minimal semantic projection (uuid, title, origin, source_ref, trust, review_state). Fields may be explicit or derived; see `docs/CORE_CONTRACT.md`.
- State axes: orthogonal and policy-driven via vault settings; policies define which axes are enabled, locked, or forced.
- Derived / overlay metadata: system-owned overlays such as `zone`, recency, or salience are computed from signals and remain outside the core contract.
- Agent reasoning operates on Core-6 + state axes + policy profiles (see `docs/NOTE_KIND_POLICIES.md`) + derived overlays.

## Note Kind Policies (policy profiles)
- Note kinds are policy profiles, not schemas. `kind` routes policy and does not define structure.
- State axes are orthogonal and selectively enabled by policy per kind.
- Policies can lock axis values and gate agent read/write permissions; defaults live in vault settings (vault-as-GUI).
- See `docs/NOTE_KIND_POLICIES.md` for policy profile examples.

## Planes and Metadata Surfaces
- Vault plane (Obsidian): the human graph of linkable notes; minimal human frontmatter is allowed/encouraged, but the system does not require heavy YAML. Notes belong here when the user might want to read or link them directly.
- External corpus plane: imported newsletters/emails/PDFs/raw docs that should be searchable and usable for answers but should not appear as notes. These objects live only in Stores/AMG with origins such as `origin: external_newsletter` and review states like `external_raw`.
- Human frontmatter vs system metadata: frontmatter is for user-facing fields (Core-6 plus optional policy axes like kind/status/priority); system metadata (signals, zone inference inputs, relations, promotions, usage counts) remains in SetDB/AMG and Stores. Core-6 remains a projection ({uuid, title, origin, source_ref, trust, review_state}) and is not the full truth.

### Note Log in the metadata mirror
- For each object/uuid in the vault there is a matching `uuid.md` in the metadata mirror (`System/Metadata/VaultMirror/<vault-relative path>/`).
- The same file is both metadata mirror and per-note log: it collects agent runs, promotion history, provenance, and any future satellite sync evidence so the machine history follows the object regardless of backend.
- The Note Log is portable Markdown that can move via Git between instances even when SetDB/AMG or other Stores differ.

## Reality-MVP Architecture Components
1) **Vault ingestion** — CLI/agent path to ingest selected Obsidian folders, normalize into Core-6 envelopes, persist in ObjectStore, emit Outbox events, chunk/index into VectorIndex, and keep provenance intact.
   - Targeted ingest is available via `ingest-vault-paths` for specific markdown files (reuses the same pipeline; first v5.1 watcher-ready step and the entrypoint watchers will call).
   - Panel/runtime entrypoint: `panel run-many` runs the same PanelAgent parse/runtime for multiple notes (emit-only supported) and remains the manual CLI hook for multi-note runs. Watcher auto-run treats AI-fenced notes as candidates once `WATCHER_AUTO_EXEC=1` is armed and only `ai_panel_auto_run: never` (`ai_panel: { auto_run: never }`) blocks the run.
   - Registry watcher: config-driven loop (`configs/watchers.yaml`, `python -m app.cli watcher run`) emits `panel.scan.requested` and `ingest.vault.changed`, writes heartbeat + tick logs, and enqueues DB outbox events. JSONL outbox is audit-only.
   - Legacy snapshot watcher (`vault-watcher-run`) is dev-only and not used in runtime start-system flows.
2) **External corpus ingest (minimal)** — a small drop folder/pipeline for real external documents ingested as `external_raw` objects, stored in ObjectStore and indexed without surfacing as vault notes (txt/md drop-folder CLI implemented; newsletters/PDFs can extend the same path).
3) **ASK API** — FastAPI endpoint returning answer text plus sources `{uuid, title, origin (vault/external), zone overlay if known, path/source_ref}` and latency; uses hybrid retrieval over both planes with an in-process HybridStore warmed from `store_objects` on first use. Zone overlays are planned but not yet populated in responses.
4) **Observability backend** — status service that aggregates per-store object counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency; exposed via CLI and interim GUI.
5) **Interim GUI** — simple FastAPI-served page (root `/`) that shows status (object counts, last ingest, ASK stats) and an ASK input with answers + visible sources; explicitly a temporary observability/interaction surface.
6) **Panel action catalog & watcher settings** — the canonical action catalog (`docs/settings/panel-actions.md`) + `vault/@Settings/watchers.md` describe allowed `watcher_allowed` actions, auto-run env (`WATCHER_AUTO_EXEC`), and outbox paths; `python -m app.cli settings-explain` and `python -m app.cli settings-validate` emit provenance + validation output for reviews.
All Reality-MVP components run on the existing PER-loop agents (Normalizer, Classifier, Chunker, CitationChecker, Indexer, Reviewer, Promotion Agent) and Store abstraction (ObjectStore, VectorIndex, RelationIndex) with Outbox-driven events and Projector/Planner/Reasoning layers kept as additive overlays.
Advanced zone logic, reflection workflows, serendipity, and collaboration are deferred until the Reality-MVP foundation is solid.

## Archival Baseline (SoT v4.5A Canon)
The sections below retain the v4.5A Canon details as a historical baseline; invariants still apply unless superseded by the Reality-MVP notes above.

## Purpose & Principles
- Human-first and agentic PKM: agents stay assistive, preserve author context, and only advance maturity when a reviewer signs off.
- Observability-first to drive transparency: every agent emits structured audit spans plus deterministic fixtures so regressions reproduce in CI.
- Core-6 contract & UUID identity: each object carries the Core-6 envelope (uuid, title, origin, source_ref, trust, review_state), whether explicit or derived, and a stable UUID threaded through stores and events.
- Store abstraction & Outbox events: ObjectStore, VectorIndex, and RelationIndex share a Store interface, while the Outbox broadcasts change events for asynchronous consumers.
- Separation of trust and audit: trust levels gate promotion; audit trails remain append-only so reviewers can replay any decision independently.

## Core Architecture

### Runtime Surfaces
Centralized reference for HTTP apps and ports during local development and docker-compose runs.

#### HTTP Apps
| Module | Variable | Purpose | Primary Routes / Notes | How to Run |
| --- | --- | --- | --- | --- |
| `app.main` | `app` | Reality-MVP PKM HTTP API (status + ASK + interim GUI) | `/healthz`, `/readyz`, `/api/health`, `/api/status`, `/search`, `/api/ask`, `/docs`, `/openapi.json` (and `/` serves static dashboard; `/api/ingest` still optional for internal tooling) | `uvicorn app.main:app --reload --port 18000` (docker-compose maps container `8000` → host `18000`) |
| `app.legacy_http` | `app` | Legacy agent/interesting/demo endpoints | `/agent/health`, `/interesting`, `/dashboard`; uses stub repo in lifespan | `uvicorn app.legacy_http:app --reload --port 18001` (dev-only) |
| `app._legacy.main` | `app` | Deprecated pre-Reality API with rate limits/metrics | `/`, `/health`, `/version`, `/context`, `/items`, `/ingest`, `/search`, agent/ui routes; requires DB + settings | `uvicorn app._legacy.main:app --reload` (not recommended for new runs) |
| `api.app` | `app` | WS golden-data demo API | `/query` returns mock answer + citations from `golden/` | `uvicorn api.app:app --reload --port 8001` when needed |

#### Ports
| Service | Purpose | Default Port | How it’s exposed / notes |
| --- | --- | ---: | --- |
| Reality-MVP HTTP API | PKM status + ASK endpoints | 18000 | Run locally via `uvicorn app.main:app --reload --port 18000`; docker-compose exposes container `8000` on host `18000`. |
| Postgres (app DB) | Stores/agents persistence | 15432 | `db` service in `docker-compose.yaml` listens on 5432 in-container; default DSN `postgresql+psycopg://app:app@localhost:15432/app`. |
| OTLP collector (optional) | Traces via OpenTelemetry Collector | 4318 (HTTP) / 4317 (gRPC) | Endpoints configured in `otelcol.yaml`; point trace exporters at `http://localhost:4318` when running a collector. |
| Prometheus (optional) | Metrics scrape endpoint | 9090 | `ops/observability/docker-compose.yaml` publishes Prometheus on 9090. |
| Grafana (optional) | Observability UI | 3000 | `ops/observability/docker-compose.yaml` publishes Grafana on 3000 with admin/admin defaults. |

This table supersedes the prior `docs/PORTS.md` listing.

### Agents
- Normalizer — accepts capture payloads, enforces Core-6 fields, and strips unsafe metadata.
- Classifier — tags object type, topic facets, and routing hints for downstream agents.
- Chunker — segments normalized text into retrieval-ready spans plus embedding metadata stubs.
- Deduper — compares against prior hashes and emits relation records for duplicates or merges.
- CitationChecker — validates outbound references and attaches citation debt metrics.
- Indexer — materializes embeddings, syncs ObjectStore + VectorIndex, and raises `index.embedding.created` (legacy alias: `index.object.embedded`).
- Reviewer — enforces maturity gates, toggles trust levels, and prepares Projector contracts.
- Projector — publishes curated packets to downstream surfaces (docs, API, knowledge packs).
- PromotionAgent — final arbiter that commits promotion decisions to audit + Outbox while coordinating cooldowns.

### Store Layer
ObjectStore persists object envelopes and agent decisions; VectorIndex stores chunk vectors plus embedding metadata; RelationIndex captures graph edges (duplicate_of, cites, derived_from) for query-time traversal. Each store implements CRUD via the Store abstraction so the same agent code works against in-memory dicts or Postgres-backed engines.

### Event Choreography
1. `ingest.object.created` records capture acceptance and seeds the PER loop.
   - `ingest.object.deleted` signals explicit vault-note deletion (path/uuid) so downstream consumers can react without inferring from missing state.
2. `ingest.object.normalized`, `.classified`, `.chunked`, `.deduped`, `.citation_checked` mark completion of each agent and carry `trace_id` plus payload diff.
3. `index.embedding.created` signals VectorIndex writes and unlocks downstream consumers (legacy alias: `index.object.embedded`).
4. `promote.pending` captures Reviewer approval; `promote.done` finalizes PromotionAgent moves and informs subscribers such as search indexing or set sync.
- All events carry `instance_id` from `SettingsBundle.instance.id` (default `home`) so audit/Outbox can mark which runtime emitted the event and prepare master/satellite without changing the vault UX.

### PromotionAgent Rules
- Idempotent writes: promotion can be retried safely because target maturity and storage side effects are computed deterministically from audit trails.
- Cooldown windows: move requests within the same five-minute window are coalesced to prevent thrash when upstream agents reclassify the same object.
- `move_policy` guardrails: `move_policy=advance_only` prohibits demotions outside manual overrides, while `move_policy=force` is reserved for maintenance tasks and always logs a privileged audit entry.

## Ingestion Pipeline (PER loop)
Every agent follows Plan → Execute → Reflect. Plan inspects the latest event plus Core-6 envelope to decide whether work is required, Execute performs the mutation using the Store layer, and Reflect writes audit spans, metrics, and Outbox entries. Data hand-offs are immutable payloads: Normalizer emits `normalized_object`, Chunker emits `chunk_set`, Deduper adds a `relation_patch`, CitationChecker appends `citation_report`, and Indexer produces an `embedding_batch`. The Reviewer consumes the cumulative context to assert maturity, then Projector and PromotionAgent close the loop. Failed executions requeue themselves by emitting a retryable event with the same `trace_id`.

### Note Ingestion Defaults
- Obsidian notes (including vault-alpha ingest) are auto-healed before Panel runs: the frontmatter `uuid` is written or retained via the YAML round-trip helpers (always as `uuid: [[<uuid>]]`), preferring any existing `uuid`/`id` even when mirrors disagree.
- Notes without UUIDs are still ingested and snapshotted; the ingest pipeline materializes the `uuid` into the note frontmatter (wikilink) and mirror before proceeding so identity stays stable across runs.
- Vault ingest stores an ingest fingerprint (text SHA + file mtime) in mirrors and the Store; skips only apply when the Store already has an object and those fingerprints agree with the freshly computed fingerprint. `--force` bypasses fingerprint/store checks, reingests everything, and is the recovery path for “new DB + old mirrors.”
- `note_moves_enable` defaults to false in runtime/global settings; Planner demotes move/rename/re-file steps to log-only and Promotion logs `promote.skip.move` instead of moving files.
- Malformed frontmatter is tolerated: invalid YAML is skipped with a warning and reported in the ingest summary rather than crashing the run.
- Ingest errors are recorded (counts + paths) in the ingest summary; reruns can resume from already-processed notes (via `resume_from` in code paths) while finishing remaining items.
- Operators can enable moves later by setting `note_moves_enable: true` in `vault/@Settings/global` (propagates into generated runtime settings after `python -m app.cli settings compile`; the `runtime/settings/` directory is generated and not committed).

### Diarization-aware Chunking (v4.6-C)
When `DIARIZE_ENABLE=1`, the ingestion pipeline now feeds diarization metadata (speaker, start, end) into `speaker_aware_chunks()` so spans are cut on speaker changes or size boundaries (O(n) over segment length). Each emitted chunk carries `{speaker,start,end,speaker_segments}` metadata that flows through `ingest_and_chunk()` to indexing, and the audit stream (`text.chunk.created`) records `speaker_count` so reviewers can trace diarization coverage. With the flag disabled, `build_chunks()` preserves the legacy token/character splitter to keep defaults inert and deterministic.
Oversized per-speaker segments are deterministically pre-split to respect `max_chars`; proportional start/end timestamps keep timelines monotonic without re-reading audio.

### Reasoning Layer (cross-agent capability + DeliberationAgent)
Reasoning is a cross-cutting capability every agent can use for planning, critique, and reflection. The layer is multi-mode (`app/reasoning/models.py`) rather than a single JSON extractor. `ReasoningMode` defines supported modes and `ReasoningRun` captures each run (id, mode, trace_id, object_uuids, steps, result, status/error). The router `run_reasoning(...)` in `app/reasoning/provider.py` orchestrates:

- `claims`: existing claims/evidence/inferences extraction (backed by `ReasoningInput` + `ReasoningOutput`); still fixture-backed for mock runs (`data/golden/reasoning_samples.jsonl`) and Ollama-backed locally.
- `review`: lightweight review/critique of a note (summary/issues/suggestions), mock-deterministic in CI, LLM-backed locally.
- `ranking`: candidate ranking with reasons, mock-deterministic in CI, LLM-backed locally (SetEvaluator consumes this).
- `planning`: reserved/TBD.

Calls include `agent` and `kind` (e.g., `reasoning.claims`, `reasoning.review`, `reasoning.ranking`) for tracing. The pipeline still gates on `REASONING_ENABLE=1` and stores claims outputs in the ReasoningStore; other modes feed agents directly (Reviewer, SetEvaluator) while remaining observable via the JSONL trace. DeliberationAgent is the specialized multi-step ASK agent that uses the Reasoning Layer to take multiple hops, and the same pattern is reused by Reviewer, SetEvaluator, and Planner.

Invariants:
- `claims` is successful (`status="ok"`) only when at least one claim or evidence exists; fully empty `{claims:[], evidence:[], inferences:[]}` is `status="failed"`.
- `ranking` is successful only when the ranking list is non-empty and contains at least one non-empty reason; otherwise `status="failed"`.

## Orchestrator V2 Design (Preview)
- Parallel step execution with deterministic scheduling and replay.
- Compensation/rollback hooks for multi-step plans.
- Checkpointing and resumption for long-running plans.
- Structured retry policy for idempotent steps.
- Flagged rollout: `ORCHESTRATOR_VERSION=v1|v2` (preview only).
- Placeholder: `docs/ORCHESTRATOR_V2.md`.

## Persistence & Execution Modes
- `STORE_BACKEND=memory` is the default for CI and unit tests; it instantiates in-memory implementations of ObjectStore, VectorIndex, and RelationIndex with deterministic UUID seeds.
- `STORE_BACKEND=pg` connects to Postgres/pgvector for full-fidelity runs; migrations guarantee schema parity with the memory structs.
- VectorIndex persistence is optional JSONL snapshots: set `INDEX_PERSIST_PATH` when writing batches and `INDEX_PERSIST_LOAD` to bootstrap warm caches across runs.
- `audit_log()` always writes to the configured sink, falling back to `logs/audit.jsonl` when stdout/file destinations are unavailable, ensuring no audit gap.
- The LLM layer defaults to `LLM_PROVIDER=mock` with fixture responses for deterministic CI; production enabling switches providers via env, while `llm_retry()` applies exponential backoff and caps at three attempts per request.

## Retrieval Layer (Rerank & Hybrid Search)
Hybrid search merges BM25 (FTS) plus vector similarity, returning distinct object IDs with score provenance. `RerankerProvider` now ships a matrix of deterministic adapters (`none`, `mock_ce`, `ce_local`, `ce_http`) that are injected via dependency wiring; reranking remains inert until `RERANK_ENABLE=1`. Operators select providers with `RERANK_PROVIDER`, keep cost bounded using `RERANK_TOP_K`, and rely on `ce_local` when they need a deterministic cross-encoder heuristic during CI. `apply_optional_rerank()` (located in `app/retrieval/hybrid_rerank_hook.py`) is called at the end of `hybrid_search` after unioning lexical + vector matches; invariants: never drop items, only reorder the first `TOP_K`, and maintain stable IDs for downstream caching. The v4.6 track keeps the same plug-in model so tests can swap mocks without touching query code, while production can point to an HTTP cross-encoder when approvals land.

### Rerank Hook Placement
The adapter `app/retrieval/hook_adapter.py::maybe_rerank(query, items)` sits on the final step of `hybrid_search` after BM25/vector scores are normalized and merged. By default it returns items untouched; when `RERANK_ENABLE` is set it delegates to `apply_optional_rerank()` so PromotionAgent and downstream caches always observe deterministic payloads (id, text, score, snippet, metadata). Memory-mode CI keeps determinism because the mock cross-encoder is pure Python and respects the provided ordering contracts.

## Observability & CI
JSONL audit logs capture `trace_id`, agent name, inputs, and outputs for each PER step; correlated `span_id`s map to structured metrics for latency and retries. Deterministic CI runs use `pytest -q -m "not pg"`, memory stores, and mock LLMs to ensure reproducible timings. Outbox processing meets QAS-010 by keeping ingest-to-index latency ≤ 2 s, while search endpoints monitor QAS-003 with p95 latency < 250 ms under hybrid retrieval. Telemetry dashboards watch agent failure rates and promotion cooldown breaches so regressions are caught before shipping.
Runtime status lives in `app.observability.status_service`: it aggregates per-plane object counts (vault/external), ingest run timestamps/errors (via ingest summaries), and ASK latency/error counts. The `status` CLI command and interim GUI (root `/`, static HTML + JS under `app/web/static/index.html`) call this backend to show a human-readable snapshot.

## A2A / Agent-to-Agent Protocol (v4.8)
A2A runs as an internal message bus over the same Stores + Events + the PER loop. When `A2A_ENABLE=1`, the Outbox registers an additional channel that carries envelopes between agents without bypassing audit or promotion invariants, and every agent can opt into message handling via `handle_agent_message()` while continuing to emit the standard ingest events. The canonical schema (request/response/error) plus audit events (`agent.request.created`, `agent.response.created`, `agent.error.created`) now ship in-tree so tests can exercise protocol hooks while routing/orchestrator wiring remains feature-gated.

### Envelope Events
- `agent.request.created` — emitted when an agent wants follow-up work from another agent; carries `request_id`, `trace_id`, desired capability, and payload summary.
- `agent.response.created` — emitted when the responding agent finishes work; includes `request_id`, `trace_id`, and a summarized response payload.
- `agent.error.created` — emitted when a follow-up request fails; includes error details, stack trace, and metadata for audit replay.

## MCP (Model Context Protocol) Surface (v4.9)
The PKM runtime exposes itself as an MCP server so external tools can orchestrate ingest/search flows without bespoke adapters. MCP endpoints mirror the internal Store/Agent APIs (e.g., `pipe_note`, `search_notes`, `get_claims`, `promote_object`, `list_relations`) and sit behind the same auth + audit envelope as the CLI.
Running with `MCP_ENABLE=1` starts an MCP server process bound to the local runtime; tool metadata describes inputs/outputs using the canonical schema so editors like Obsidian or ChatGPT can call them directly. Deterministic mocks remain available for CI so MCP startup is a no-op unless explicitly toggled.

## Note Update Path (Panel Runtime + UUID integrity)
`NoteUpdateService` builds on that by treating the note UUID as the durable identity: `process_note_update()` loads the note, checks an optional expected path (stale detection), hydrates prior snapshots from `tmp/note_update_snapshots`, and runs `handle_panel_update()` before writing the updated markdown + snapshot. The `note-update` CLI batches this over one or more files (`python -m app.cli note-update vault/Inbox --glob '*.md'`), emits per-note status, and summarizes processed/changed/dispatch counts. This is the same entrypoint future filesystem watchers will call when they notice edited notes, so behaviour stays deterministic whether triggered manually or automatically.
Two commands exist on purpose: `panel-update` runs the AI panel in isolation for a single note (instruction/actions/logg) without snapshots, stale detection, or watcher orchestration, while `note-update` runs the canonical UUID-first pipeline with snapshots, stale detection, and panel + event dispatch that note-scan and future watchers rely on. Use this quick guide to pick the right tool.
- use `panel-update` when:
- you only want to operate on a single file without invoking snapshots, stale detection, watcher logic, or UUID holistic update logic,
- you are developing panel actions and want a tight feedback loop.
- use `note-update` when:
- you need deterministic UUID-first behaviour consistent with watcher-triggered runs,
- you want stale detection and snapshots with `tmp/note_update_snapshots`,
- you want behaviour consistent with note-scan and future watchers.

## Runtime Topology (Reality-MVP)
- The compose stack runs db (pgvector), api (FastAPI on 8000 mapped to 18000), watcher (registry watcher), and worker (DB outbox consumer) on Colima-backed Docker.
- `/api/health` now surfaces watcher heartbeats, worker heartbeats, and DB/LLM readiness checks so the Status service can report liveliness with deterministic probes.
- Operator scripts (`scripts/start_full_system.sh`, `scripts/gap_test_alpha.sh`) wrap the watcher→worker→index→/api/ask loop, log diagnostics, and guard against missing sources so the architecture is observable without manual digging.
