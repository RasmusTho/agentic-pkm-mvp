State: SoT v4.10 Reality-MVP (baseline locked) with the active forward line tracked at v5.5 (PanelAgent planner pipeline + CLI-first orchestration with watcher track).
# Architecture — SoT v4.10 Reality-MVP

Historic SoT snapshots and older plans live in `docs/archive/`; the 4.x ladder history is in `docs/history/SOT_4X_HISTORY.md`. Forward-looking plan lives in `docs/ROADMAP.md`.
They are kept for reference but are not considered active truth for the current SoT v4.10 Reality-MVP.
External dependencies, deployment topology, and human-facing surfaces are captured in `docs/SYSTEM_DESIGN_v4.10.md`; this document focuses on internal architecture and runtime contracts.

System map: `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md` covers the high-level Yggdrasil modules and flows; this document remains the detailed technical architecture.

`docs/HUMAN-FLOWS.md` captures the intended human experience and interaction flows; any architecture change that alters user-facing behavior should be validated against that contract before shipping.

This architecture focuses on the runtime and data model for the Mimer module (the Obsidian vault + ingestion/indexing/agents) within the broader Yggdrasil system. A high-level overview of Yggdrasil’s modules and flows lives in `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`, and human interaction patterns in `docs/HUMAN-FLOWS.md`.

### Instance model (internal master/satellite plumbing)
- SettingsBundle includes `instance` with `id` (e.g., `home`, `work`, `laptop`) and `role` (`master` or `satellite`).
- Default when nothing is configured: `id="home"` and `role="master"`, matching the Reality-MVP single-runtime focus.
- Scope: internal plumbing that informs events/logs and future sync topology; no change to the Obsidian surface or frontmatter.

## Contracts (concept anchors)

Architecture describes how things are wired today; these documents define what must remain stable as implementations evolve:

- `docs/PROJECT_KERNEL.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`

## Component Catalog
- See `docs/COMPONENTS.md` for the canonical, human- and machine-readable list of active components (stores, agents, embeddings, rerankers, eval stack, observability). Update it when wiring new component entrypoints under `app/components/*`.
- The outbox/event system uses a common envelope (`event`, `trace_id`, `source`, `timestamp`, `payload`, `meta`) defined in `app/events/schema.py` and enforced by architecture tests; emitters should write via outbox helpers to preserve the contract.

## SoT lines
- **SoT v4.10 Reality-MVP (baseline locked)** — single-user PKM with stable vault ingest, minimal external ingest, hybrid retrieval + ASK with sources/latency, observability/status surfaces (CLI/API/GUI), and orchestrator runtime V1. Operational acceptance: soak vault ingest and external newsletter/PDF samples. Collaboration/multi-user deferred.
- **SoT v5.0 PanelAgent Runtime V1 (first v5.x baseline)** — sits on top of the locked v4.10 baseline; Panel runtime interprets `panel.intent.created`, fans promotion actions to `promote.intent.created`, emits `panel.intent.executed`/`panel.action.*`/`panel.log.created`, and writes AI panel logs (`panel_logs`) that connect the note UI to internal intents.
- **SoT v5.x Agentic PKM (active forward line, currently through v5.5)** — Agentic flows (PanelAgent v5+), Satellite Sync (`docs/PROTOCOL_SATELLITE_SYNC.md`), and Yggdrasil modules (Munin/Brokkr/Tyr/Heimdall) that extend the v4.10 backbone; richer orchestration (LangGraph + MCP ToolProvider) and reasoning live here. The forward line now includes a watcher/agent infra track that builds on v5.0: v5.1 watcher-ready ingest/panel flows (including targeted ingest via `ingest-vault-paths` and multi-note panel CLI), v5.2 snapshot-based CLI polling watcher MVP (`vault-watcher-run` driving ingest + panel), v5.3 explicit policy for auto-panel via frontmatter gating watcher runs, v5.4 watcher hardening/ergonomics (dry-run, max-notes guard, structured summaries), and v5.5 planner pipeline + CLI-first orchestration.

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

## Concurrency & Idempotency
- Concurrency guards are a v5.5D gate for watcher auto-exec and orchestration.
- Events MUST carry `event_id` and consumers MUST deduplicate; note writes MUST fail safe on version mismatch.
- See `docs/CONCURRENCY.md` for the required patterns and testing strategy.

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
   - Panel/runtime watcher entrypoint: `panel run-many` runs the same PanelAgent parse/runtime for multiple notes (emit-only supported) and will be the panel-side hook for Vault Watcher batches; watcher auto-run is gated by frontmatter policy (`ai_panel_auto_run`).
   - Vault Watcher CLI: `vault-watcher-run` (v5.2) performs snapshot-based change detection, calls `ingest-vault-paths` for changed notes, optionally runs `panel run-many`, then refreshes the snapshot for polling/scheduler use; v5.4 adds dry-run and max-notes guard plus structured summaries.
2) **External corpus ingest (minimal)** — a small drop folder/pipeline for real external documents ingested as `external_raw` objects, stored in ObjectStore and indexed without surfacing as vault notes (txt/md drop-folder CLI implemented; newsletters/PDFs can extend the same path).
3) **ASK API** — FastAPI endpoint returning answer text plus sources `{uuid, title, origin (vault/external), zone overlay if known, path/source_ref}` and latency; uses hybrid retrieval over both planes with an in-process HybridStore warmed from `store_objects` on first use. Zone overlays are planned but not yet populated in responses.
4) **Observability backend** — status service that aggregates per-store object counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency; exposed via CLI and interim GUI.
5) **Interim GUI** — simple FastAPI-served page (root `/`) that shows status (object counts, last ingest, ASK stats) and an ASK input with answers + visible sources; explicitly a temporary observability/interaction surface.
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
- Indexer — materializes embeddings, syncs ObjectStore + VectorIndex, and raises `index.object.embedded`.
- Reviewer — enforces maturity gates, toggles trust levels, and prepares Projector contracts.
- Projector — publishes curated packets to downstream surfaces (docs, API, knowledge packs).
- PromotionAgent — final arbiter that commits promotion decisions to audit + Outbox while coordinating cooldowns.

### Store Layer
ObjectStore persists object envelopes and agent decisions; VectorIndex stores chunk vectors plus embedding metadata; RelationIndex captures graph edges (duplicate_of, cites, derived_from) for query-time traversal. Each store implements CRUD via the Store abstraction so the same agent code works against in-memory dicts or Postgres-backed engines.

### Event Choreography
1. `ingest.object.created` records capture acceptance and seeds the PER loop.
2. `ingest.object.normalized`, `.classified`, `.chunked`, `.deduped`, `.citation_checked` mark completion of each agent and carry `trace_id` plus payload diff.
3. `index.object.embedded` signals VectorIndex writes and unlocks the Reviewer.
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
- Operators can enable moves later by setting `note_moves_enable: true` in `vault/@Settings/global` (propagates into `runtime/settings/global.yaml`).

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
- `agent.response.created` — produced when the receiving agent completes the requested action and publishes outputs or state diffs in an append-only fashion.
- `agent.error` — emitted when the receiving agent cannot complete the requested action; includes retry hints and failure metadata so the Orchestrator can branch deterministically.
- `agent.critique.created` — optional critique or blocker event that lets downstream reviewers see peer feedback before a promotion decision.
Envelopes reuse Core-6 metadata and append an `a2a.intent` field so determinism and replay remain intact.

### Pipeline Hooks
Agents subscribe to A2A messages through the same PER scheduler: Plan inspects incoming envelopes (if enabled), Execute performs the requested action, and Reflect emits the response event plus standard audit spans. A2A never replaces Store interactions; it simply allows agents to chain themselves without introducing side channels. Hooks remain inert unless the flag is set, ensuring default CI paths stay unchanged.

### Sample Chain
Classifier can request deeper deliberation by emitting `agent.request.created(intent="reason")` for DeliberationAgent; once processed, DeliberationAgent answers via `agent.response.created` and can critique via `agent.critique.created`. PromotionAgent or Projector may then issue a follow-up request to Projector for packaging, giving a deterministic Classifier → DeliberationAgent → Projector chain that is fully audited yet optional, even though structured reasoning is a cross-cutting capability every agent uses.

## A2A Message Flow
The A2A protocol is intentionally narrow and mediated entirely by the Orchestrator. Envelopes remain internal:
- `agent.request.created` describes the capability being requested, the payload summary, and the Core-6 identifier/trace.
- `agent.response.created` captures deterministic outputs or state diffs in an append-only fashion.
- `agent.error` communicates blocked work plus retry metadata so the Orchestrator can branch or halt safely.
Agents never exchange envelopes peer-to-peer; the Orchestrator inspects the active plan, routes envelopes via `handle_agent_message()`, persists audit spans, and guarantees deterministic replays for CI. Flags keep orchestration inert until `A2A_ENABLE=1`, preserving the legacy ingest flow by default.

## MCP Integration Layer — v4.9
The PKM runtime exposes itself as an MCP server so external tools can orchestrate ingest/search flows without bespoke adapters. MCP endpoints mirror the internal Store/Agent APIs (e.g., `pipe_note`, `search_notes`, `get_claims`, `promote_object`, `list_relations`) and sit behind the same auth + audit envelope as the CLI.

### MCP Server Surface
Running with `MCP_ENABLE=1` starts an MCP server process bound to the local runtime; tool metadata describes inputs/outputs using the canonical schema so editors like Obsidian or ChatGPT can call them directly. Deterministic mocks remain available for CI so MCP startup is a no-op unless explicitly toggled.

### MCP Client Inside the Act Phase
Agents gain an optional ToolProvider wrapper that can dispatch MCP tool calls from within the Act phase. Calls remain synchronous, respect retry budgets, and emit `mcp.tool.invoked` audit lines. When disabled, the ToolProvider reverts to a no-op stub, keeping the act phase identical to current behaviour.

### Orchestrator-driven MCP Calls
When plans contain MCP tool steps, the Orchestrator invokes those tools through the ToolProvider on behalf of the currently scheduled agent, captures results, and resumes the workflow. Supported actions include vault writes/file ops, search, ingestion/normalization helpers, analytics routines, or curated external API queries. These calls either replace or complement the historical CLI commands while sharing the same audit envelope. Every invocation is audited with the originating plan step and is fully mocked under CI so the Planner Agent can rely on tool access without sacrificing determinism.

### Deterministic Tool Chains
`ToolProvider` abstracts whether calls hit the local MCP server, a mock provider, or an injected client. CI defaults to the mock provider so planners and agents can validate tool choreography without sockets. The abstraction keeps MCP additive: enable it to let external editors drive ingestion, search, relation updates, or promotion checks; leave it off to continue CLI-only execution.

### Compatibility Note
Legacy CLI workflows (`python -m app.cli pipe ...`) remain supported until the LangGraph-based Orchestrator runtime becomes the default surface. Operators can keep `PLANNER_ENABLE`, `A2A_ENABLE`, and `MCP_ENABLE` unset to preserve historical behaviour, then progressively opt into Planner Agent + Orchestrator + MCP flows without breaking scripted ingestion.

### ASK CLI flow
The `python -m app.cli ask "..."` command emits an `ask.query.received` event, optionally lets FlowProfiles pick a pattern, and routes the resulting plan through the Orchestrator. The CLI injects tool settings so MCP vault writes stay mocked by default, but operators can opt in via `--enable-mcp-vault`/`MCP_VAULT_ENABLE` plus a `VAULT_ROOT`. After execution it prints the selected flow/pattern, the plan summary, and any resulting `mcp.vault.append_note` paths so teams can demo the full question -> plan -> agent/tool -> vault pipeline without bespoke glue.

## LLM-Driven Planning Layer — v4.9
Planning is embedded directly into the PER loop, turning “Plan → Act → Reflect” into a concretely orchestrated, LLM-generated step. When `PLANNER_ENABLE=1`, the planner executes before each agent cycle, producing a structured plan that lists which agent should run, which MCP tools to call, and whether any A2A requests must be issued.

### Planner Inputs
The planner consumes the current object context (Core-6 + latest payload), a RelationIndex snapshot, declared agent capabilities, and the backlog of recent A2A envelopes. These inputs are encoded as JSON per the existing Reasoning Provider schema to keep prompts deterministic. `PlannerInput` (defined in `app/planner/provider.py`) mirrors this bundle and is the canonical payload handed to any planner backend.

### Plan Schema & Tool Descriptors
`app/planner/schema.py` defines the persisted plan contract: `Plan` (with `PlanMetadata`), `PlanStep`, and `ToolDescriptor`. Steps carry `kind=agent_call|tool_call|decision|note`, optional `agent/intent`, MCP tool names (e.g., `mcp.vault.append_note`) plus structured `tool_args`, dependencies, and metadata so plans replay deterministically. MCP tool descriptors live under `app/planner/tools.py` as a static registry (`MCP_TOOL_DESCRIPTORS`) the Planner Agent references when suggesting tool steps; each descriptor ships with a JSON-schema-like shape, explicit `allowed_args`, and a deterministic `mock_result` so the executor can validate payloads without touching real MCP tools. Tests assert that plan steps referencing those names remain valid even before we wire actual MCP execution.

### Planner Outputs & Execution
Planner responses must validate against the Plan schema, so downstream executors see a uniform structure regardless of backend. Plans may include `tool_call` and `agent_call` steps so multi-agent workflows chain without bespoke glue, and they can reference MCP tools by name through the ToolProvider abstraction. If the planner is disabled, the classical round-robin PER scheduler runs unchanged. When `PLANNER_ENABLE=1`, `app.agents.pipeline.maybe_plan_for_object()` emits a plan plus `planner.plan.created`, and when `ORCHESTRATOR_ENABLE=1` the same pipeline calls `maybe_execute_plan()` so the Orchestrator replays the plan immediately after ingest (deterministically mocked in CI). The runtime can also be invoked directly via `orchestrate-external`, which builds and executes a plan using the same executor contract.

### Deterministic Backends & Flags
`app/planner/provider.py` exposes `MockPlanner` (deterministic fixtures for CI) and `LLMPlanner` (Ollama-backed when `PLANNER_PROVIDER=llm` and `LLM_PROVIDER!=mock`). The provider falls back to the mock backend and emits `planner.plan.fallback` when misconfigured or when LLM output fails validation. `PLANNER_ENABLE=0` keeps the planner inert; when enabled, planner calls are audited via `planner.plan.created` (intake) plus `planner.plan.error`/`planner.plan.fallback` when issues occur so reviewers can trace every orchestrated decision alongside MCP and A2A traces.

## Planner Agent vs Orchestrator
### Planner Agent (LLM-driven)
An LLM-powered Planner Agent ingests the requested goal or intent, Core-6 metadata, the latest object text, a RelationIndex snapshot, recent reasoning outputs (`claims`, `evidence`, `inferences`), and the agent capability graph. It emits a structured plan object that enumerates execution steps, target agents, required A2A envelopes, any MCP tool invocations, dependencies, preconditions, and stop conditions. CI always runs the mock backend so the resulting plan remains deterministic, and the entire stage is gated behind `PLANNER_ENABLE`.

### Orchestrator (deterministic executor)
The Orchestrator is the deterministic execution layer (current PER-loop derivative with a LangGraph runtime on the horizon) that consumes the plan, schedules referenced agents, persists state transitions, and delivers A2A messages. It coordinates branching, retries, and structured state transitions while remaining backward compatible with the CLI `pipe` workflow until operators opt into the new runtime. Whenever the plan references MCP tools or additional agents, the Orchestrator sequences the calls, records audit spans, and guarantees replayability.

### Orchestrator Runtime — Execution Model (v4.10A)
AgentConfigs now guard agent_call steps: before invoking an agent, the orchestrator resolves its vault-defined AgentConfig and enforces enabled/flow/event boundaries. Misconfigured or disabled agents yield structured permission errors instead of crashes, keeping human-declared constraints in control while tool/decision steps remain unchanged.

`app/orchestrator/runtime.py` hosts the Orchestrator class plus an executor. Plans are validated up front (unique IDs, dependency order, required agent/tool metadata). Each step emits `orchestrator.step.started|finished|error` with the plan/step identifiers so auditing can reconstruct the control flow. Execution defaults to deterministic MCP/A2A mocks, but now supports internal tools with side effects:
- `agent_call` steps dispatch via `send_agent_request` (emitting `agent.request.created`) and immediately route through the default Agent handler, which responds with `agent.error.created` / `error_type=not_implemented`.
- MCP tool calls validate descriptors/args, emitting `mcp.tool.call.started|finished` and returning `mock_result` unless explicitly enabled (vault append).
- Internal tools include `internal.ingest_external` which runs the external drop-folder ingest pipeline and returns a summary; this powers the `orchestrate-external` CLI dual-run path alongside the direct `ingest-external` command.
- Decision/note steps remain structured audit payloads without mutating stores.

The current choreography is serialized and flag-gated (`PLANNER_ENABLE` + `ORCHESTRATOR_ENABLE`). Future LangGraph/parallel scheduling layers can reuse the same executor contract while preserving determinism.

```
Planner Agent
      │
      │ plan (Plan/PlanStep schema)
      ▼
Orchestrator.run_plan()
      ├─ agent_call → send_agent_request() → Agent.handle_agent_request() → agent.error.created (default stub)
      └─ tool_call  → MCP descriptor validation → mcp.tool.call.started/finished (mock_result, no side effects)
```

### Planner ↔ Reasoning Layer
Planner prompts reuse Reasoning Layer payloads so the Planner Agent stays grounded in deterministic state. The Planner inspects `ReasoningInput` bundles plus Core-6 frontmatter and relation graphs before proposing any step, which makes downstream audits straightforward and keeps plan generation tightly coupled to earlier reasoning outputs.

### Vault-first Flow & Agent Settings

Flow profiles now live in the vault under `vault/_system/flows/*.md`. Each Markdown file exposes YAML frontmatter parsed by `app.settings.flow_profiles` into a `FlowProfile` that focuses on intent, suggested agent/tool patterns, planner mode hints, and available prompt templates:

```yaml
---
flow_id: ingest
name: Ingest pipeline
event_triggers:
  - ingest.object.created
intent: Turn new raw text into structured, searchable knowledge.
suggested_patterns:
  - name: standard_ingest
    steps:
      - agent:normalizer
      - agent:classifier
planner_mode:
  strictness: advisory
  max_steps: 8
prompt_profiles:
  - id: ingest-default
    prompt_template_ref: prompts/planner/ingest-default.md
---
```

FlowProfiles express a human-defined strategy rather than a rigid plan: intent documents the goal, `suggested_patterns` lists example sequences the planner may follow, `planner_mode` sets advisory limits/strictness, and `prompt_profiles` enumerates the planner prompts available for that flow. Planner/Orchestrator remain unchanged in this PR; these profiles are read-only guidance until wired in.

Agent definitions follow the same docs-as-code contract in `vault/_system/agents/*.md`, loaded via
`app.settings.agents` into `AgentConfig` instances:

```yaml
---
agent_id: planner
agent_type: planner
flows:
  - ingest
  - promotion
tools:
  - summarize
  - planner.scratchpad
prompt_template_ref: planner.prompts.default
---
```

For this slice the Planner and Orchestrator keep their previous behaviour; the new loaders simply make
the vault-backed configuration available for upcoming integrations.

## AI panel: human-first note interaction
Notes may optionally expose a lightweight AI panel so humans drive intent directly in Markdown without custom syntax. Panels are delimited by forgiving AI comment fences (`%% ...AI... %%` after trimming spaces), where the first fence opens a panel, the second closes it, the third opens the next, etc. Inside a panel the schema is:
- **AI instruction** — free-text instructions that describe what the human wants from the system for this note.
- **AI actions** — markdown checkbox actions (`- [ ] ...` / `- [x] ...`) that the human can tick to request a discrete move.
- **AI log** — chronological bullet log of what the system already executed for the note.

Example:
```
%% AI:Start %%
## AI instruction
...
## AI actions
...
## AI log
...
%% AI:End %%
```

Fences are tolerant to label variations (any `%%` line containing `ai`); legacy notes that only use the headings without fences are still parsed as panels, but new panels should use fences. Panel content is not part of the knowledge base and must not be indexed or used for QA.

`PanelState` (pydantic) normalises these sections so agents can diff old vs. new states deterministically. The `PanelAgent` parses prior/current note bodies, emits `PanelIntent` records for newly-checked actions or instruction edits, and proposes updated Markdown by removing one-shot actions and appending a simple log entry (e.g., `- Action: "..."`). The agent remains local/in-memory for now: it is not wired to Planner/Orchestrator yet, but its output objects are ready for the future event pipeline.

Vault-first mappings under `vault/_system/panel-actions/*.md` (with docs fallback `docs/settings/panel-actions.md`) translate checkbox text into canonical event types. When PanelAgent detects a newly checked action it enriches the `PanelIntent` with that mapping and synthesizes structured `OutboxEvent` envelopes (see `app/events/schema.py` for the canonical `event/trace_id/source/timestamp/payload/meta` shape) so upcoming wiring can hand intents to Planner/Orchestrator deterministically.

`handle_panel_update()` wraps this flow: it parses the panel, applies mappings, and when `PANEL_EVENTS_ENABLE=1` it dispatches each PanelAgent event through `handle_event()` so the existing Planner/Orchestrator pipeline runs (down to mock MCP tool calls in tests). With the flag disabled the integration stays dry-run and only returns rewritten markdown plus intent metadata, keeping panel edits local until the operator opts in.

`python -m app.cli panel-update path/to/note.md --old-path path/to/old.md` exposes this in the CLI for manual runs: it reads the note, executes `handle_panel_update()`, writes back the AI actions/log updates, and reports how many panel events were created/dispatched (respecting `PANEL_EVENTS_ENABLE` and `EVENT_ORCHESTRATOR_ENABLE`).

`NoteUpdateService` builds on that by treating the note UUID as the durable identity: `process_note_update()` loads the note, checks an optional expected path (stale detection), hydrates prior snapshots from `tmp/note_update_snapshots`, and runs `handle_panel_update()` before writing the updated markdown + snapshot. The `note-update` CLI batches this over one or more files (`python -m app.cli note-update vault/Inbox --glob '*.md'`), emits per-note status, and summarizes processed/changed/dispatch counts. This is the same entrypoint future filesystem watchers will call when they notice edited notes, so behaviour stays deterministic whether triggered manually or automatically.

### Panel update vs Note update — when to use which
Two commands exist on purpose: `panel-update` runs the AI panel in isolation for a single note (instruction/actions/logg) without snapshots, stale detection, or watcher orchestration, while `note-update` runs the canonical UUID-first pipeline with snapshots, stale detection, and panel + event dispatch that note-scan and future watchers rely on. Use this quick guide to pick the right tool.

**Use `panel-update` when…**
- you want to test the AI panel behaviour directly,
- you are debugging checkbox mapping, instruction parsing, or log formatting,
- you only want to operate on a single file without invoking snapshots, stale detection, watcher logic, or UUID holistic update logic,
- you want fast iteration on panel designs.

**Use `note-update` when…**
- you want the system to update the note "for real",
- you want snapshot-aware, UUID-first safe writes with stale detection,
- you want panel output + event dispatch + orchestrator plans,
- you want behaviour consistent with note-scan and future watchers.

## Runtime & Infrastructure
- Compose/ports/startup details live in docs/INFRASTRUCTURE.md.
- The compose stack runs db (pgvector), api (FastAPI on 8000 mapped to 18000), and worker (outbox consumer) on Colima-backed Docker.

## Health & heartbeats
- `/api/health` now surfaces watcher heartbeats, worker heartbeats, and DB/LLM readiness checks so the Status service can report liveliness with deterministic probes.
- The Outbox now publishes `index.object.embedded` and `index.embedding.failed` events; dashboards, gap tests, and fitness gates read those events to confirm the embedding pipeline is working end to end.
- Operator scripts (`scripts/start_full_system.sh`, `scripts/gap_test_alpha.sh`) wrap the watcher→worker→index→/api/ask loop, log diagnostics, and guard against missing sources so the architecture is observable without manual digging.
