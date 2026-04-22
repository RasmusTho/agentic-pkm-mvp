State: SoT v5.5 Reality-MVP baseline locked (watcher safety, panel action provenance, and concurrency hardening); v5.6 delivery line closed; v6 is the active design and planning direction. Post-v5.6 follow-ups are tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening.
Doc role: Core SoT
Authority: Active runtime architecture source of truth for the current baseline and runtime contracts; wins over roadmap and historical references on current-state questions.
Owner: Runtime / architecture SoT
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-04-22
Last verified against: docs/ENVIRONMENTS.md, docs/STATUS.md, docs/PANEL_AGENT.md, docs/EVENTS.md, docs/OBSERVABILITY.md, docs/RETRIEVAL.md, docs/ROADMAP.md, docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md, docs/FINDING_AND_REORIENTING/README.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, app/chat/read_only_cognition.py, app/cli/__init__.py, app/orchestrator/runtime.py, app/orchestrator/v2_runtime.py, app/orchestrator/executor.py, app/retrieval/capability.py, app/watcher/registry.py, app/workers/outbox_worker.py, tests/chat/test_read_only_chat_cognition.py, tests/events/test_event_envelope_versioning.py, tests/events/test_outbox_consumer_contract.py, tests/orchestration/test_plan_timeout_budget.py, tests/orchestration/v2/test_plan_timeout_budget.py, tests/retrieval/test_retrieval_capability.py, tests/retrieval/test_relation_provenance_metadata.py, Makefile, merged PRs #547/#548/#549/#550/#551/#552/#553/#555, current repo state at 59966e9 on 2026-04-22, closed retrieval issues #534/#537/#539, closed Orchestrator follow-up issue #540, closed Chat scaffold issue #542, closed ReasoningFacade adoption issue #543, and closed settings validation issue #546

# Architecture — SoT v5.5 Reality-MVP baseline (v5.6 delivered, v6 active design)

This document is the active architecture source of truth for the SoT v5.5 Reality-MVP baseline and the place where current runtime contracts are defined.

Historic SoT snapshots and older plans live in `docs/archive/`; the 4.x ladder history is in `docs/history/SOT_4X_HISTORY.md`. Forward-looking plan lives in `docs/ROADMAP.md`.
Those documents are kept for reference but are not active truth for the current baseline. If a historical or roadmap document conflicts with this document on current-state runtime architecture, this document wins.

This architecture focuses on the runtime and data model for the Mimer module (the Obsidian vault + ingestion/indexing/agents) within the broader Yggdrasil system.

## Executive Summary

The current architecture is a local-first Mimer runtime, not the full Yggdrasil target system:
- the shipped baseline is vault-first ingestion, registry watcher, DB outbox, worker/indexing,
  PanelAgent, ASK, status/health, and guarded note mutation;
- the current data shape should be read through the three artifact surfaces: human vault notes,
  system companion/continuity artifacts, and rebuildable runtime DB/index projections;
- `ReasoningFacade`, LangGraph, A2A, MCP descriptors, and Orchestrator V2 are real repo surfaces,
  but their current status is mixed: some are active runtime paths, some are flagged pilots, and
  some are scaffolding or reference contracts rather than broad production rollout;
- the planned architecture continues toward capability-based composition, separate Panel and Chat
  interaction surfaces, governed execution, and relation-aware context without treating ASK,
  retrieval, a single agent, or historical AMG/SetDB terminology as the architectural center.

Proposal:
- keep v5.5 as the locked operational baseline,
- treat v5.6 as the closed stabilization and enablement delivery line for safe automation,
  shared reasoning seams, flagged Orchestrator V2 pilot work, A2A/MCP contract hardening,
  and reproducible local verification,
- move unresolved work into explicit post-v5.6 follow-ups instead of reading it as an
  active v5.6 blocker; recent post-v5.6 closures include the A2A lifecycle cleanup (#359),
  the V2 timeout discriminator bug (#456), and v6-driven current-state domain/zone bugs
  (#435/#436/#437),
- keep v6.0 as the target-state architecture lane for interaction/cognition/execution/memory/governance
  separation, capability reuse, Chat canvas planning, Deep Agent introduction, commitments, and richer
  context/relation modeling.

Non-current material is deliberately not restated here: historical system maps, `AMG`/`SetDB`
lineage, legacy snapshot watcher posture, and old module names are background only unless a current
owner document explicitly promotes them.

Related documents and authority boundaries:
- `docs/DESIGN_PRINCIPLES.md` defines the stable design rules for modularity, flexibility, authority separation, and documentation layering. Use it before changing architecture wording or roadmap framing.
- `docs/HUMAN-FLOWS.md` is the user-facing behavior contract. Any architecture change that alters user-visible behavior should be validated against it before shipping.
- `docs/ENVIRONMENTS.md` defines the active `dev` / `test` / `prod` environment model, including environment invariants, allowed variance, persistence/runtime separation, and production safety expectations.
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
- `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md` defines the current timeout handling, SLA boundaries, and observable timeout behavior across orchestration surfaces (executor-level per-tool timeout, orchestrator constraints, and A2A limitations).
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

Validation boundary note:
- architecture tests protect current runtime invariants and boundary contracts
- they do not, by themselves, prove that the broader human needs in `docs/HUMAN-FLOWS.md` are satisfied
- when a human-need acceptance scenario reaches beyond the active baseline, keep that distinction explicit in docs and test posture instead of narrowing the scenario to fit the current wiring

At minimum, the following must stay true:
- the DB outbox remains the canonical queue for runtime side effects,
- watcher, worker, and ASK paths remain observable through health/status surfaces,
- note updates remain deterministic and guarded by idempotency/write-safety rules,
- docs and tests continue to enforce the same current-state boundaries.

### Instance model (internal master/satellite plumbing)
- SettingsBundle includes `instance` with `id` (e.g., `home`, `work`, `laptop`), `role` (`master` or `satellite`), and `environment` (`dev` or `prod`).
- Defaults when nothing is configured: `id="home"`, `role="master"`, `environment="prod"`, matching the Reality-MVP single-runtime focus and production-safe baseline.
- Environment selection: resolved from `PKM_ENVIRONMENT` (explicit), `PKM_SETTINGS_PROFILE` mapping (lab→dev, operator→prod), or default (prod). See `docs/ENVIRONMENTS.md`.
- Scope: internal plumbing that informs events/logs, feature gates, and future sync topology; no change to the Obsidian surface or frontmatter.

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
- The outbox/event system uses a common envelope (`event`, `event_id`, `trace_id`, `source`,
  `timestamp`, `payload`, `meta`, and version metadata for new/changed families) defined in
  `app/events/schema.py` and enforced by architecture tests; emitters should write via outbox
  helpers to preserve the contract.

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
- environment (`dev` vs `prod`) is an operational/runtime distinction, not a different ontology of artifacts or a different semantic model

See also:
- `docs/HUMAN-FLOWS.md`
- `docs/ENVIRONMENTS.md`
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
- **SoT v5.x Agentic PKM (v5.6 delivered, post-v5.6 follow-up mode)** — Agentic flows extend the v5.5 baseline through PanelAgent, guarded watcher automation, shared reasoning seams, A2A/MCP contract hardening, and a flagged Orchestrator V2 pilot. Satellite Sync (`docs/plans/PROTOCOL_SATELLITE_SYNC.md`) and broader Yggdrasil module expansion remain planned/conceptual, not baseline runtime. Shipped v5.6 pieces include targeted ingest via `ingest-vault-paths`, multi-note panel CLI, registry watcher defaulting, watcher safety gates, planner pipeline + CLI-first orchestration, `ReasoningFacade`, descriptor-based MCP/tool execution, bounded A2A in-process routing, sync-latency validation, deterministic runtime health checks, V2 checkpoint/resume hardening, V2 retry/backoff observability, the V2 timeout discriminator fix, and optional plan-level orchestration timeout budgets. MCP ToolProvider integration, remote MCP multiplexing, broad A2A delivery semantics, and statistical/infra sync hardening remain post-v5.6 follow-ups.

### Runtime watcher choice
- Registry watcher is the runtime default; start-system flows and Docker compose use `python -m app.cli watcher run` with `configs/watchers.yaml`.
- Settings tiering enforcement: watcher dev/lab tuning env vars are ignored in normal runtime (`PKM_SETTINGS_PROFILE=operator`) and require explicit `PKM_SETTINGS_PROFILE=lab`. See `docs/ENVIRONMENTS.md`; this current settings-profile split is a partial control mechanism, not the full environment contract.
- Legacy snapshot watchers (`vault-watcher-run`, `vault-watcher-daemon`, runtime-loop) are dev-only, require `PKM_SETTINGS_PROFILE=lab`, and are not used in runtime start-system flows or as production surfaces.
- Store object table is canonicalized to `store_objects`; legacy `objects` rows are best-effort backfilled when `store_objects` is empty so runtime reads/writes stay on one table.
- Legacy `scripts/fs_watcher.py` note lifecycle operations route through `VaultPort` (`FilesystemVaultAdapter`) rather than direct sink/pass-through writes.
- DB outbox is canonical in runtime; JSONL outbox is audit/diagnostic only.

### Environment contract (current architecture reading)
- `dev`, `test`, and `prod` are the active environment model in the SoT. Their purpose, invariants, and allowed variance are defined in `docs/ENVIRONMENTS.md`.
- Environment changes may affect runtime topology, provider choice, diagnostics, fixture data, and tuning, but they MUST NOT change artifact semantics, event contracts, provenance rules, or write-safety boundaries.
- Vault surface, companion/system surface, runtime stores, and operational artifacts must remain separable by environment even when the underlying architecture is otherwise shared.
- Production runtime must prefer conservative behavior, explicit gating, and recoverable failure over convenience.

### Architecture Statement: Bounded Agents on Shared Foundations
- The architecture is expected to include multiple bounded agents with narrow responsibilities rather than one central general agent.
- Shared scaffolding such as `AgentState`, LangGraph control patterns, common prompts, policies, and capabilities should provide the reusable foundation for those agents.
- Tools/MCP: tools are actions an agent chooses from within its LangGraph or equivalent bounded control flow; they should not be hard-wired at the pipeline/Orchestrator level beyond routing envelopes.
- Foundational capabilities such as ingestion, indexing, retrieval, reasoning support, and execution/governance support remain first-class even when they are not expressed as standalone agents.
- Current adoption is phased and mixed: ASK and PanelAgent are active runtime LangGraph surfaces; Reviewer/pilot and older graph wrappers exist for selected agent lanes, CLI/dev use, or tests; most ingest/index production paths still run as deterministic pipelines until later rollout phases.

## Agent Implementation Pattern (Current Direction)
- Agents MUST preserve external event contracts and Outbox envelopes during migrations.
- Agents that already use LangGraph should keep explicit state and deterministic tool/event boundaries.
- `ReasoningFacade` now exists as the shared reasoning seam; any expansion of that seam's baseline role or additional shared LangGraph scaffolding must update this document and the owning agent specs in the same change.
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
- Companion notes plus vault notes are the portable file-based continuity set and must be sufficient
  to rebuild runtime DB/index state from scratch.
- Runtime DB state may help rebuild a missing companion note during recovery, but that is a
  fallback path rather than proof of DB primacy.
- For the broader mirror/receipt/projection semantics, see `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
  and `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`.

## Current Runtime Surfaces
1) **Vault ingestion** — CLI/agent path to ingest selected Obsidian folders, normalize vault notes into Core-6 projections, persist them in ObjectStore, emit Outbox events, chunk/index into VectorIndex, and keep provenance intact.
   - Targeted ingest is available via `ingest-vault-paths` for specific markdown files (reuses the same pipeline; first v5.1 watcher-ready step and the entrypoint watchers will call).
   - Panel/runtime entrypoint: `panel run-many` runs the same PanelAgent parse/runtime for multiple notes (emit-only supported) and remains the manual CLI hook for multi-note runs. Watcher auto-run treats AI-fenced notes as candidates once `WATCHER_AUTO_EXEC=1` is armed and only `ai_panel_auto_run: never` (`ai_panel: { auto_run: never }`) blocks the run.
   - Registry watcher: config-driven loop (`configs/watchers.yaml`, `python -m app.cli watcher run`) emits `panel.scan.requested` and `ingest.vault.changed`, appends `watcher.run` audit events for status counting, writes heartbeat + tick logs, and enqueues DB outbox events. JSONL outbox is audit-only.
   - Legacy snapshot watcher (`vault-watcher-run`) is dev-only and not used in runtime start-system flows.
2) **External corpus ingest (minimal)** — a small drop folder/pipeline for real external documents ingested as `external_raw` runtime objects, stored in ObjectStore and indexed without surfacing as vault notes (txt/md drop-folder CLI implemented; newsletters/PDFs can extend the same path).
3) **ASK API** — FastAPI endpoint returning answer text plus sources `{uuid, title, origin (vault/external), zone overlay if known, path/source_ref}` and latency; uses hybrid retrieval over both planes with an in-process HybridStore warmed from `store_objects` on first use. `zone` is passed through when present on the hit payload, but derived zone coverage is not guaranteed baseline behavior.
4) **Observability backend** — status service that aggregates per-store projection counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency; exposed via CLI and interim GUI.
5) **Interim GUI** — simple FastAPI-served page (root `/`) that shows status (object counts, last ingest, ASK stats) and an ASK input with answers + visible sources; explicitly a temporary observability/interaction surface.
6) **Panel action catalog & watcher settings** — the canonical action catalog (`docs/settings/panel-actions.md`) + `vault/@Settings/watchers.md` describe allowed `watcher_allowed` actions, auto-run env (`WATCHER_AUTO_EXEC`), and outbox paths; `python -m app.cli settings-explain` and `python -m app.cli settings-validate` emit provenance + validation output for reviews.
All current runtime surfaces build on the same Store abstraction (ObjectStore, VectorIndex, RelationIndex), event envelope, and vault-first write boundary.

## Current vs Planned Status

| Area | Actual status | Planned / non-baseline status |
| --- | --- | --- |
| Mimer runtime | Active baseline: vault ingest, registry watcher, DB outbox, worker/indexing, PanelAgent, ASK, status/health, and guarded writes. | Broader Yggdrasil module expansion remains conceptual/planned unless a current owner doc says otherwise. |
| Artifact persistence | Active reading model: human vault notes, system companion notes, and rebuildable runtime DB/index projections. | v6 target-state work refines writing/retention/system surfaces; it must not revive DB-primary or AMG-primary wording. |
| Watcher path | Registry watcher (`python -m app.cli watcher run`) is the production-facing default; legacy snapshot watchers and `runtime-loop` are lab/dev-only. | Sync and autonomy validation continue through bounded harnesses and follow-up slices. |
| PanelAgent | Active governed mutation-capable surface with action catalog, watcher gates, provenance, and write guards. | Richer cognition may support Panel later, but execution remains downstream of policy, validation, and events. |
| ASK | Active v5.x API/runtime surface over hybrid retrieval and answer composition. | Deprecated as the v6 architectural center; retrieval becomes a reusable capability. |
| Reasoning/LangGraph | `ReasoningFacade` exists; ASK and PanelAgent use LangGraph in active runtime paths; reviewer and note-hygiene reasoning now route through the shared facade seam while preserving existing write-authority boundaries. | Broader Promotion/Hygiene graph adoption remains phased and gated; facade adoption does not imply full LangGraph baseline rollout or production Deep Agent expansion. |
| Orchestrator | V1 is default. V2 is flag-selected via `ORCHESTRATOR_VERSION=v2` and includes dependency-aware parallel scheduling, event/trace compatibility, compensation/rollback, retry metadata handling, retry/backoff observability, checkpoint/resume with configurable interval persistence, and the #456 timeout-discriminator fix for documented executor `tool_timeout` errors. Per-tool timeout via `tool_timeout_seconds` and optional plan-level timeout via `plan_timeout_seconds` are supported on both V1 and V2 (see `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`). | Broad V2 adoption is not baseline. Repo-wide A2A/runtime delivery SLA remains non-baseline. |
| A2A | Internal schema and audit helpers are current-state contracts (`agent.request.created`, `agent.response.created`, `agent.error.created`); routed in-process agent calls exist where handlers are registered. | No production A2A transport, retry queue, dead-letter queue, or repo-wide delivery SLA is claimed. |
| MCP/tools | Descriptor registry, validation, deterministic/mock execution, internal tools, and gated real `mcp.vault.append_note` path exist. | MCP ToolProvider integration, dynamic discovery, remote server multiplexing, and richer versioning are planned. |
| Chat / Deep Agents | A read-only Chat cognition scaffold exists for planning/decomposition through the shared `ReasoningFacade`; it does not execute tools, write notes, emit outbox mutations, or emit promotion/action intents. | Chat is the planned canvas-shaped interaction surface; any future Chat or Deep Agent mutation remains gated through governed execution and is not part of the current scaffold. |
| Satellite sync | Instance/device plumbing and sync-latency validation harnesses exist. | Full satellite-sync behavior remains planned, not a current runtime claim. |

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

## Post-v5.6 Follow-ups (Non-baseline)

These topics are real parts of the repo and roadmap, but they are not baseline-defining architecture for the locked v5.5 runtime:
- broader Reasoning/LangGraph rollout beyond the currently active and pilot agent paths
- full A2A runtime semantics beyond the current internal schema, audit helpers, and in-process routed calls
- full MCP ToolProvider/runtime integration beyond the current descriptor registry and executor adapter behavior
- Orchestrator V2 broad adoption, and repo-wide A2A/runtime delivery SLA beyond the delivered timeout contract (`tool_timeout_seconds` plus optional `plan_timeout_seconds`)
- future satellite-sync behavior

Treat these as post-v5.6 follow-up or specialized-reference topics owned by:
- `docs/ROADMAP.md`
- `docs/plans/V56_FORWARD_LINE.md`
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`
- `docs/AGENTS.md`
- `docs/tracks/*`

## Layered System Architecture (v6 Direction)

This section describes the intended v6 direction. It does not override the locked v5.5 baseline or the delivered v5.6 contracts.

- Interaction is the primary organizing concern for the user-facing architecture; cognition and reusable capabilities support those interaction surfaces, while foundational capabilities such as ingestion and indexing remain first-class elsewhere in the system.
- The architecture is organized around five distinct concerns: interaction, cognition, execution, memory, and governance.
- LangGraph is the current and planned control-plane mechanism for deterministic orchestration and explicit runtime state progression.
- Deep Agents are a future cognition mechanism for planning, decomposition, and multi-step reasoning. They are introduced only after structural separation is in place.
- The capability layer provides reusable functions such as retrieval, reranking, and context building. Capabilities are shared building blocks, not conceptual centers of the system.
- Current retrieval capability extraction is bounded to a typed wrapper over the existing hybrid
  search path. It carries optional provenance, relation, and view-freshness diagnostics as metadata
  for future surfaces, but relation-aware ranking, orientation, and resurfacing remain future work.
- The execution layer contains controlled effectors only. Reasoning must not directly mutate notes or trigger execution.
- The memory/persistence layer is the three-surface model plus backing runtime stores: human vault
  artifacts, system companion/continuity artifacts, and rebuildable runtime projections/indexes.
  Historical `AMG`/`SetDB` language is lineage only and must not be revived as the canonical
  persistence substrate.
- The governance layer enforces policies, admissibility, provenance, approval, and auditability across mutation-capable paths.
- This structure treats Yggdrasil as a system-of-systems so the layers can evolve independently without collapsing authority boundaries.

## Interaction Surfaces

Panel and Chat should both be treated as valid user-intent surfaces; their distinction is
interaction structure (command-oriented vs canvas/co-authoring), not whether intent is
authoritative.

The compatibility details for reading Panel as the primary command surface without making it the
exclusive intent surface live in
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md`; future
hybrid Chat/Panel crossings are bounded by
`docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`.

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
- The early Deep Agent rollout starts in a read-only Chat slice because it isolates cognition from execution risk.
- Chat itself is a canvas-shaped interaction surface, not permanently read-only; future Chat-originated mutations must still pass through the governed policy, validation, and event pipeline.
- Should be read as an exploratory cognition surface first, not as a settled UI embodiment or unrestricted execution path.

## Capability Model

- Retrieval is a capability, not an agent.
- Retrieval must be reusable across Panel, Chat, and future cognition surfaces without creating another agent-specific control center.
- The shipped capability boundary preserves current hybrid retrieval behavior and result ordering;
  additive relation/provenance inputs and stale/partial-view diagnostics are observable metadata,
  not ranking authority.
- Capabilities are reusable, composable, and testable.
- Agents and orchestration layers invoke capabilities through explicit planning and state transitions.
- ASK remains a valid current runtime/API surface in the v5.x line, but it is deprecated as the architectural center for v6 direction. New design work should not rebuild retrieval around a special central agent, even if bounded agents remain common elsewhere in the system.

## Historical Material

Historical topology, older runtime surfaces, and superseded architecture detail live outside this document:
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- `docs/history/SOT_4X_HISTORY.md`

This document deliberately does not inline those older sections. For current-state questions, the active sections above are authoritative.

## GitHub Delivery Control Plane (development governance)

This section governs development-time delivery control in GitHub. It does not define runtime/system-agent behavior.
Runtime/system semantics remain owned by the existing architecture, agent, concept, and settings documents.

Development control model:

- Docs define intent, contracts, and owner boundaries.
- GitHub Issues are the canonical task contract for implementation work.
- GitHub Project v2 is the delivery state machine.
- Coding agents are the execution layer that implement bounded Issues.
- Pull requests are the implementation artifact.
- CI/test workflows are the validation loop.
- Outcomes feed back into docs, Issues, and Project state.

Canonical delivery sequence:

`Docs -> Issue -> Project -> Agent -> PR -> CI -> Feedback`

Required Issue contract:

- `Context`
- `Scope`
- `Source Anchors`
- `Constraints`
- `Acceptance Criteria`
- `Out of Scope`
- `Suggested Validation`
- `Source Docs`

Acceptance criteria must include inline `Verify:` targets so the validation path is concrete before
an Issue is marked `agent:ready`.

Required label ontology:

- type: `type:task`, `type:bug`, `type:refactor`
- priority: `prio:high`, `prio:med`, `prio:low`
- agent qualifiers: `agent:ready`, `agent:blocked`, `agent:needs-human`

Required Project state machine:

- `Backlog -> Ready -> In Progress -> Review -> Done`

Optional Project field:

- `Agent State`: `Idle`, `Running`, `Waiting`

Guardrails for builder agents:

- Project `Status` is the primary lifecycle signal.
- `agent:ready` qualifies an Issue for pickup only when `Status=Ready`.
- `In Progress` covers active implementation and open PR work before explicit review handoff.
- `Review` begins only when review handoff is explicit, normally after review is requested.
- Closed or delivered work must not retain `agent:*` labels.
- Agents only pick Issues with `Status=Ready` and label `agent:ready`.
- Agents must stay within the linked Issue scope.
- Agents must respect the linked Issue constraints.
- Agents must satisfy the linked Issue acceptance criteria before claiming completion.
- No architecture-breaking or boundary-breaking work proceeds without an Issue.
- No free-form tasks are canonical; GitHub Issues are the source of truth for delivery tasks.

This GitHub control plane is a development governance layer around the repo-first/docs-as-code workflow.
It must not be confused with the runtime agent architecture described elsewhere in this document.
