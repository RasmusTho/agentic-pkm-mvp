State: SoT v5.5 Reality-MVP baseline locked (watcher safety, panel action provenance, and concurrency hardening) with the forward line now entering v5.6 LangGraph/Reasoning rollouts.
Doc role: Core SoT
Authority: Active runtime architecture source of truth for the current baseline and runtime contracts; wins over roadmap and historical references on current-state questions.
# Architecture — SoT v5.5 Reality-MVP baseline (forward line v5.6)

This document is the active architecture source of truth for the SoT v5.5 Reality-MVP baseline and the place where current runtime contracts are defined.

Historic SoT snapshots and older plans live in `docs/archive/`; the 4.x ladder history is in `docs/history/SOT_4X_HISTORY.md`. Forward-looking plan lives in `docs/ROADMAP.md`.
Those documents are kept for reference but are not active truth for the current baseline. If a historical or roadmap document conflicts with this document on current-state runtime architecture, this document wins.

This architecture focuses on the runtime and data model for the Mimer module (the Obsidian vault + ingestion/indexing/agents) within the broader Yggdrasil system.

Related documents and authority boundaries:
- `docs/DESIGN_PRINCIPLES.md` defines the stable design rules for modularity, flexibility, authority separation, and documentation layering. Use it before changing architecture wording or roadmap framing.
- `docs/HUMAN-FLOWS.md` is the user-facing behavior contract. Any architecture change that alters user-visible behavior should be validated against it before shipping.
- `docs/ONTOLOGY_RUNTIME_BRIDGE.md` is the cross-layer reading guide connecting human functions, semantic classes, persistence surfaces, and runtime contracts. It does not replace the owning SoT docs, but it should be used when architecture wording risks collapsing those layers.
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` defines the broader human-first second-brain ontology. This document uses narrower runtime and storage language where needed and should not be read as the full domain ontology.
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` defines the normalized vocabulary and explains where repo terms such as `note`, `object`, `agent`, `source`, and `promotion` drift across layers.
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` clarifies how artifacts, projections, and source roles should be distinguished when runtime/store/search layers need narrower representations.
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md` defines the forward-line artifact model, three
  surfaces, lifecycle posture, and scenario-bound authority matrix for note identity/healing.
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` defines the companion note as the first-class
  system-surface artifact for continuity and repair.
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md` clarifies how instance identity, device roles, replicas, and instance provenance should be understood without collapsing them into artifact identity.
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` clarifies how salience,
  attentional relevance, and surfacing need should be understood upstream of the runtime `zone`
  overlay.
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md` is a historical reference for external dependencies, deployment topology, and human-facing surfaces from the v4.10 foundation snapshot. It is useful background, but it is not authoritative for the current v5.5 baseline.
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md` is a historical high-level module map retained for orientation and naming continuity. It may not reflect current v5.5 wiring and should not be treated as the active system map when evaluating current behavior.

Function-first reading rule:
- `docs/HUMAN-FLOWS.md` defines what the system is meant to help the human do.
- this document defines how the currently active runtime is wired in order to support some of those
  functions.
- if implementation wording in this document starts to redefine the human purpose of the system, the
  human-flow and concept documents win.

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

## Artifact surfaces (current reading, forward-line aligned)

Read the current architecture through three artifact surfaces:
- human surface: vault notes on the Obsidian writing surface
- system surface: companion notes and related continuity/repair artifacts
- runtime surface: DB objects, chunks, embeddings, summaries, and other local operational views

The owning artifact-model plan is `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`.
This architecture doc uses that model as the forward-line reading frame and must not reintroduce a
DB-primary or single-rule identity model.

Recovery posture:
- vault note + companion note are the portable file-based continuity set
- runtime DB/index state is rebuildable from that set
- runtime state may help recover a missing companion note, but it is not semantically primary

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
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
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

## System-of-systems view

The current runtime should be read as a small system-of-systems arrangement:
- Obsidian/human editing is the human-surface environment
- system-owned companion artifacts preserve continuity and repair state in the system surface
- local runtime persistence and indexes provide the runtime surface
- watchers, workers, and ingest flows react to changed files and refresh runtime state

This repo's runtime therefore depends on clear boundaries between:
- human meaning-bearing artifacts,
- system continuity artifacts,
- and derived runtime/index artifacts

Those boundaries are narrower than the full Yggdrasil ontology, but they must remain explicit in
current architecture language.

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

## Layered reading model
- Human cognitive functions are a product-level design lens for why the system exists and what it should help the user do.
- The ontology/policy layer explains what kinds of things the runtime is dealing with and what boundaries or authority bases apply.
- The runtime orchestration layer explains how the current system coordinates bounded work through stores, events, agents, and pipelines.
- The infrastructure layer explains where persistence, transport, provider calls, and process boundaries live.
- Interaction remains architecturally primary on the user-facing side: retrieval, reasoning, ingestion, indexing, and other reusable mechanisms should be read as foundational supporting capabilities rather than as the whole organizing model of the system.
- Not every human function implies a separate runtime agent, service, or queue.
- Deterministic pipelines remain valid runtime substrate when they satisfy the same contracts more clearly and safely than richer agent structures.

## Operational topology (current reality, not locked core architecture)

Current operational reality includes heterogeneous device roles and practical transport choices.
The authoritative user-facing description lives in `docs/HUMAN-FLOWS.md`, while this architecture
document records only the architectural consequence:
- the runtime reacts to changed files rather than treating iCloud or Git as semantically primary
- file-based eventual consistency matters more than any one transport
- device asymmetry is an operational condition, not a different ontology of artifacts

See also:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`

## Reading Rules
- This document is architecture-first, not ontology-first: terms such as `object`, `store_objects`, `agent`, and `event` refer to runtime representations and execution units unless stated otherwise.
- `Note` here usually means a human-facing vault note (`Vault Note`) in the writing/human plane.
- `Object` here usually means a runtime/store projection or ingestable unit, not the full meaning of an artifact.
- `Agent` here usually means an architectural/runtime unit; some are rich system agents, while others are closer to deterministic pipelines or execution components.
- `Review`, `promotion`, and related labels should be read as transition/process families in the runtime, not as proof that the ontology has only one lifecycle axis.

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

### Architecture Statement: Bounded Agents on Shared Foundations
- The architecture is expected to include multiple bounded agents with narrow responsibilities rather than one central general agent.
- Shared scaffolding such as `AgentState`, LangGraph control patterns, common prompts, policies, and capabilities should provide the reusable foundation for those agents.
- Tools/MCP: tools are actions an agent chooses from within its LangGraph or equivalent bounded control flow; they should not be hard-wired at the pipeline/Orchestrator level beyond routing envelopes.
- Foundational capabilities such as ingestion, indexing, retrieval, reasoning support, and execution/governance support remain first-class even when they are not expressed as standalone agents.
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
- Current runtime retrieval uses `ASK_DOMAIN_SCOPE` and `bridge_domains` as compatibility labels
  for a narrower operational-scope filter and explicit inclusion mechanism.
- Read these as current implementation terms, not as the full human context model.
- By default, retrieval remains conservative and excludes results outside the active operational
  scope unless explicit inclusion is present.
- The runtime now includes an additive relation-store seam for broader belonging metadata via
  optional `sphere_membership` memberships on artifacts.
- This seam represents broader sphere/context participation only. It does not replace operational
  scope, does not embed permission semantics, and does not make retrieval or ranking relation-driven
  by default in the current baseline.
- Absence of `sphere_membership` data is a normal state and must preserve current runtime behavior.
- Panel/UI sections are a control surface and MUST NOT be indexed as knowledge.
- When writes are blocked (WriteGuard / `safe_mode`), reviewed notes MUST NOT be mutated without explicit intent/APPLY.

## Reality-MVP Orientation
- Primary focus: make ingestion of the real Obsidian vault stable, add a minimal external ingest path, expose a reliable ASK API, and ship observability plus an interim GUI so the system is usable end to end.
- A derived `zone` overlay is applied on top of the knowledge base; it is computed from signals
  such as usage, recency, and trust rather than from folder names.
- Two planes: Obsidian vault as the human graph (LYT + PARA) with minimal human frontmatter, and an external corpus plane (newsletters/emails/PDFs) that is indexed and retrievable but never rendered as Obsidian notes.
- Metadata backbone lives in the current Store-backed data layer.
  Core-6 frontmatter remains a projection for humans at the vault/runtime boundary (see
  `docs/CORE_CONTRACT.md`), while system metadata (signals, relations, usage counts, agent
  reflections) sits in rebuildable runtime data structures and stores.
- Historical `SetDB/AMG` terminology may still appear in lineage docs, but it should not be read as
  the canonical name of the current baseline architecture.
- Collaboration/multi-user stays out of scope for Reality-MVP; the current work is single-user, vault-first reliability.

## Abstraction boundaries (current direction)

- `KnowledgePort` is the canonical write/read boundary for vault-facing note operations. Healing
  writes and companion-note writes must route through it or approved helpers built on top of it.
- `SyncLayer` is the operational abstraction that reacts to file changes and sync consequences
  without hard-coding one transport as the semantic source of change. In current reality this is
  realized through watcher/worker flows over local files and synced replicas.
- `EmbeddingProvider` is the abstraction boundary for embedding generation. Embeddings are
  provider/model-tagged derived runtime artifacts and must not be treated as stable identity
  records. In current code this is expressed through the embedding config/runtime stack rather than
  a single named interface.

## Zone Overlay
- The runtime currently exposes a derived `zone` overlay for attentional proximity and surface
  shaping.
- Read `zone` as a runtime projection over salience signals, not as the canonical ontology of what
  matters.
- Historical or compatibility language may describe these overlays with temperature-like labels such
  as `hot`, `warm`, or `cold`, but those metaphors are not the authoritative architectural
  semantics.
- Zones are orthogonal to workflow/status handling and to the state axes. They must not be used as
  a proxy for `review_state` or `maturity`, and they remain separate from temporal value
  (ephemeral vs normal vs evergreen longevity).
- A note may be high-value and peripheral, or short-lived and currently active, without forcing one
  axis to stand in for the other.
- Zones are derived from runtime signals such as recency, relations, and usage; they are not
  mandatory folder/tag names and do not dictate file layout.

## Core Contract, State Axes, and Overlays
- Core contract: Core-6 is the minimal semantic projection (uuid, title, origin, source_ref, trust, review_state). Fields may be explicit or derived; see `docs/CORE_CONTRACT.md`.
- State axes: orthogonal and policy-driven via vault settings; policies define which axes are enabled, locked, or forced.
- Current promotion compatibility rule: promotion paths now write `maturity` as the canonical standing
  sink when a standing transition is known (for example `evergreen`), while `review_state` remains
  the canonical review/mutation posture field. Legacy notes or payloads that still express standing
  through `review_state: evergreen` remain accepted as compatibility input, but canonical writes
  normalize that state to `maturity: evergreen` plus `review_state: reviewed`.
- Planner/orchestrator normalization keeps external event compatibility (`promote.intent.created`)
  while routing internal promotion work through explicit transition semantics (`request_promotion_transition`
  with `transition.family = promotion` and `transition.target_maturity`).
- Compatibility-only legacy `review_state` inputs still accepted at normalization boundaries are:
  `evergreen`, `processed`, `promoted`, `inbox`, and `logged`. Current runtime callers should not
  produce those values as new canonical state-axis outputs.
- Workflow/status handling such as inbox intake remains distinct from the state axes. Where the
  current runtime still needs inbox-like filtering or routing, treat it as compatibility or
  workflow metadata rather than as the canonical meaning of `review_state`.
- Execution plans are runtime orchestration artifacts. They must not be read as equivalent to the
  human commitment/project layer described in `docs/PROJECT_KERNEL.md` and the commitment concept
  contracts.
- Derived / overlay metadata: system-owned overlays such as `zone`, recency, or salience are computed from signals and remain outside the core contract.
- Agent reasoning operates on Core-6 + state axes + policy profiles (see `docs/NOTE_KIND_POLICIES.md`) + derived overlays.

## Note Kind Policies (policy profiles)
- Note kinds are policy profiles, not schemas. `kind` routes policy and does not define structure.
- State axes are orthogonal and selectively enabled by policy per kind.
- Policies can lock axis values and gate agent read/write permissions; defaults live in vault settings (vault-as-GUI).
- See `docs/NOTE_KIND_POLICIES.md` for policy profile examples.

## Planes and Metadata Surfaces
- Vault plane (Obsidian): the human graph of linkable notes; minimal human frontmatter is allowed/encouraged, but the system does not require heavy YAML. Notes belong here when the user might want to read or link them directly.
- External corpus plane: imported newsletters/emails/PDFs/raw docs that should be searchable and
  usable for answers but should not appear as notes. These ingestable artifacts live in the
  Store-backed runtime data layer with origins such as `origin: external_newsletter` and review
  states like `external_raw`.
- Human frontmatter vs system metadata: frontmatter is for user-facing fields (Core-6 plus optional
  policy axes like kind/status/priority); system metadata (signals, zone inference inputs,
  relations, promotions, usage counts) remains in the runtime data layer and stores. Core-6 remains
  a projection ({uuid, title, origin, source_ref, trust, review_state}) and is not the full truth.
- Broader sphere/context belonging can now be stored additively in the relation store as optional
  `sphere_membership` memberships keyed by artifact `uuid`; this is enablement toward richer
  relation-first context handling, not the full v6.0 target state.

### Companion note in the system surface
- For each tracked vault note/uuid the forward-line model defines a companion note under
  `vault/_system/companions/<uuid>.md`.
- The companion note is a first-class system artifact for continuity and repair, not merely a
  convenience cache or derived runtime projection.
- Companion notes plus vault notes must be sufficient to rebuild runtime DB/index state from
  scratch.
- Runtime DB state may help rebuild a missing companion note when available, but that is a recovery
  path rather than proof of DB primacy.
- Earlier `VaultMirror` path language should be read as transitional compatibility language for the
  broader mirror/projection concept; see `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` and
  `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`.

## Current Runtime Surfaces
1) **Vault ingestion** — CLI/agent path to ingest selected Obsidian folders, normalize vault notes into Core-6 projections, persist them in ObjectStore, emit Outbox events, chunk/index into VectorIndex, and keep provenance intact.
   - Targeted ingest is available via `ingest-vault-paths` for specific markdown files (reuses the same pipeline; first v5.1 watcher-ready step and the entrypoint watchers will call).
   - Panel/runtime entrypoint: `panel run-many` runs the same PanelAgent parse/runtime for multiple notes (emit-only supported) and remains the manual CLI hook for multi-note runs. Watcher auto-run treats AI-fenced notes as candidates once `WATCHER_AUTO_EXEC=1` is armed and only `ai_panel_auto_run: never` (`ai_panel: { auto_run: never }`) blocks the run.
   - Registry watcher: config-driven loop (`configs/watchers.yaml`, `python -m app.cli watcher run`) emits `panel.scan.requested` and `ingest.vault.changed`, writes heartbeat + tick logs, and enqueues DB outbox events. JSONL outbox is audit-only.
   - Legacy snapshot watcher (`vault-watcher-run`) is dev-only and not used in runtime start-system flows.
2) **External corpus ingest (minimal)** — a small drop folder/pipeline for real external documents ingested as `external_raw` runtime objects, stored in ObjectStore and indexed without surfacing as vault notes (txt/md drop-folder CLI implemented; newsletters/PDFs can extend the same path).
3) **ASK API** — FastAPI endpoint returning answer text plus sources `{uuid, title, origin (vault/external), zone overlay if known, path/source_ref}` and latency; uses hybrid retrieval over both planes with an in-process HybridStore warmed from `store_objects` on first use. Zone overlays are planned but not yet populated in responses.
4) **Observability backend** — status service that aggregates per-store projection counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency; exposed via CLI and interim GUI.
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

## Layered System Architecture (v6 Direction)

This section describes the intended v6 direction. It does not override the locked v5.5 baseline or active v5.6 contracts.

- Interaction is the primary organizing concern for the user-facing architecture; cognition and reusable capabilities support those interaction surfaces, while foundational capabilities such as ingestion and indexing remain first-class elsewhere in the system.
- The architecture is organized around five distinct concerns: interaction, cognition, execution, memory, and governance.
- LangGraph is the current and planned control-plane mechanism for deterministic orchestration and explicit runtime state progression.
- Deep Agents are a future cognition mechanism for planning, decomposition, and multi-step reasoning. They are introduced only after structural separation is in place.
- The capability layer provides reusable functions such as retrieval, reranking, and context building. Capabilities are shared building blocks, not conceptual centers of the system.
- The execution layer contains controlled effectors only. Reasoning must not directly mutate notes or trigger execution.
- The memory layer remains AMG plus backing stores as the canonical persistence substrate.
- The governance layer enforces policies, admissibility, provenance, approval, and auditability across mutation-capable paths.
- This structure treats Yggdrasil as a system-of-systems so the layers can evolve independently without collapsing authority boundaries.

## Interaction Surfaces

### Panel

- Embedded in note.
- Driven by explicit intent.
- Produces structured outputs such as actions and proposals.
- Is one important governed mutation surface in the planned model.
- May use richer cognition later, but execution still flows through policy, validation, and the event pipeline.
- Should be read as a command and intent-capture surface, not as a generic chat surface.

### Chat

- External to note.
- Optimized for exploratory reasoning.
- May span multi-note context.
- Starts as a read-only sandbox for early Deep Agent rollout because it isolates cognition from execution risk.
- May later participate in governed mutation paths, but that should not be assumed in the current baseline.
- Should be read as an exploratory cognition surface first, not as a settled UI embodiment or unrestricted execution path.

## Capability Model

- Retrieval is a capability, not an agent.
- Retrieval must be reusable across Panel, Chat, and future cognition surfaces without creating another agent-specific control center.
- Capabilities are reusable, composable, and testable.
- Agents and orchestration layers invoke capabilities through explicit planning and state transitions.
- ASK remains a valid current runtime/API surface in the v5.x line, but it is deprecated as the architectural center for v6 direction. New design work should not rebuild retrieval around a special central agent, even if bounded agents remain common elsewhere in the system.

## Historical Material

Historical topology, older runtime surfaces, and superseded architecture detail live outside this document:
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- `docs/history/SOT_4X_HISTORY.md`

This document deliberately does not inline those older sections. For current-state questions, the active sections above are authoritative.
