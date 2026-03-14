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
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md` is a historical reference for external dependencies, deployment topology, and human-facing surfaces from the v4.10 foundation snapshot. It is useful background, but it is not authoritative for the current v5.5 baseline.
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md` is a historical high-level module map retained for orientation and naming continuity. It may not reflect current v5.5 wiring and should not be treated as the active system map when evaluating current behavior.

## System Context (Current)

The current runtime sits inside a small local system boundary:
- Human-facing surfaces:
  - the Obsidian vault as the canonical writing and reading surface,
  - the CLI for operator and developer workflows,
  - the HTTP API for ASK, health, and status.
- Runtime components in this repository:
  - ingestion, watcher, panel, ASK, promotion, worker, and store-facing application code,
  - event emission and observability hooks,
  - settings and contract enforcement.
- Runtime dependencies outside this repository:
  - Postgres/pgvector for canonical store persistence and DB outbox,
  - the local vault filesystem,
  - optional local or remote LLM/embedding providers,
  - optional observability stack components such as Prometheus and Grafana.

In the current v5.5 baseline, the implemented center of gravity is still the Mimer module: vault-first ingestion, indexing, retrieval, and agent behavior around the Obsidian knowledge surface. Other Yggdrasil modules remain useful conceptual boundaries, but they are not equally implemented in the current runtime.

## Fitness Functions

Fitness functions capture the high-level criteria that must hold true for the runtime to be considered healthy.

In the current baseline, architecture owns the invariants and boundaries, while enforcement is expressed in:
- `docs/TESTING.md` for CI and regression gates
- `docs/STATUS.md` for the current rollout posture and baseline lock
- `docs/OPERATIONS.md` for runtime checks and operator-facing verification

At minimum, the following must stay true:
- the DB outbox remains the canonical queue for runtime side effects,
- watcher, worker, and ASK paths remain observable through health/status surfaces,
- note updates remain deterministic and guarded by idempotency/write-safety rules,
- docs and tests continue to enforce the same current-state boundaries.

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
- Current rendered/runtime-facing diagram companion: `docs/DIAGRAMS.md`.
- Terminology in the map:
  - `Omgivning (utanför systemgräns)` = actors/services outside this system.
  - `Systemlandskap / driftsberoenden (ej i kodbasen)` = runtime dependencies owned by the system but not part of this repository (for example Postgres, Obsidian, vault filesystem).
  - `Koddomän (denna kodbas)` = components implemented in this repository.
- The map also marks:
  - Internal interface abstractions (`VaultPort`, `KnowledgePort`, store protocols).
  - Representative internal functions used as runtime seams between modules.

## SoT lines
- **SoT v5.5 Reality-MVP baseline (locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guardrails on top of the stable vault ingest, hybrid retrieval/ASK, observability/status surfaces, and orchestrator runtime V1.
- **Reality-MVP foundation snapshot** — single-user PKM with stable vault ingest, minimal external ingest, hybrid retrieval + ASK with sources/latency, observability/status surfaces (CLI/API/GUI), and orchestrator runtime V1. Retained as foundation history; superseded by the v5.5 baseline.
- **SoT v5.x Agentic PKM (active forward line, currently entering v5.6)** — Agentic flows (PanelAgent v5+), Satellite Sync (`docs/plans/PROTOCOL_SATELLITE_SYNC.md`), and Yggdrasil modules (Munin/Brokkr/Tyr/Heimdall) that extend the v5.5 baseline; richer orchestration (LangGraph + MCP ToolProvider) and reasoning live here. The forward line includes the watcher/agent infra track: v5.1 watcher-ready ingest/panel flows (including targeted ingest via `ingest-vault-paths` and multi-note panel CLI), v5.2 snapshot-based CLI polling watcher MVP (`vault-watcher-run` driving ingest + panel), v5.3 explicit policy for auto-panel via frontmatter gating watcher runs, v5.4 watcher hardening/ergonomics (dry-run, max-notes guard, structured summaries), and v5.5 planner pipeline + CLI-first orchestration.

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

## Agent Implementation Pattern (Current Direction)
- Agents MUST preserve external event contracts and Outbox envelopes during migrations.
- Agents that already use LangGraph should keep explicit state and deterministic tool/event boundaries.
- If `ReasoningFacade` or shared LangGraph scaffolding is introduced into the active baseline, this document and the owning agent specs must be updated in the same change.
- Current agent-specific implementation detail lives in:
  - `docs/AGENTS.md`
  - `docs/PANEL_AGENT.md`
  - active settings and graph specs under `docs/settings/`

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

## Core Contract, State Axes, and Overlays
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

## Current Runtime Surfaces
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
All current runtime surfaces build on the same Store abstraction (ObjectStore, VectorIndex, RelationIndex), event envelope, and vault-first write boundary.

## Operational and Implementation Detail

The following topics are part of the current system, but their detailed behavior is owned by narrower documents:
- persistence backends, startup paths, and runtime topology:
  - `docs/OPERATIONS.md`
  - `docs/INFRASTRUCTURE.md`
- retrieval, reranking, and ASK behavior:
  - `docs/COMPONENTS.md`
  - `docs/LLM.md`
  - `docs/RETRIEVAL.md`
- note-update, panel, and promotion specifics:
  - `docs/PANEL_AGENT.md`
  - `docs/HUMAN-FLOWS.md`
- observability, health, and CI/runtime verification:
  - `docs/OBSERVABILITY.md`
  - `docs/HEALTH.md`
  - `docs/TESTING.md`

## Forward-Line Features (Non-baseline)

These topics are real parts of the repo and roadmap, but they are not baseline-defining architecture for the locked v5.5 runtime:
- richer Reasoning/LangGraph rollout beyond the currently active agents
- A2A envelopes and cross-agent routing experiments
- MCP-facing runtime surfaces
- Orchestrator V2 design and rollout
- future satellite-sync behavior

Treat these as forward-line or specialized-reference topics owned by:
- `docs/ROADMAP.md`
- `docs/plans/V56_FORWARD_LINE.md`
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`
- `docs/AGENTS.md`
- `docs/tracks/*`

## Historical Material

Historical topology, older runtime surfaces, and superseded architecture detail live outside this document:
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- `docs/history/SOT_4X_HISTORY.md`

This document deliberately does not inline those older sections. For current-state questions, the active sections above are authoritative.
