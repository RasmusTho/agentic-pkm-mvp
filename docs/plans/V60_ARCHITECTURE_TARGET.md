State: Proposed target operating model for v6.0; baseline-aware and not current runtime truth.
Doc role: Plan
Authority: Target-state architecture plan for v6.0 operating boundaries; does not override current runtime truth in `docs/ARCHITECTURE.md` or operational status in `docs/STATUS.md`.
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-04-14
Last verified against: docs/ARCHITECTURE.md, docs/STATUS.md, docs/ROADMAP.md, docs/RETRIEVAL.md, docs/PANEL_AGENT.md, docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md, docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md, docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/FINDING_AND_REORIENTING/README.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md

# v6.0 Architecture Target Operating Model

## Purpose

This document describes the target operating model for a future `v6.0` line.

It is not current runtime truth. For current-state questions:
- `docs/ARCHITECTURE.md` wins on architecture and runtime contracts.
- `docs/STATUS.md` wins on operational posture and rollout status.
- `docs/RETRIEVAL.md` and `docs/PANEL_AGENT.md` win on current subsystem behavior.

The target model is baseline-aware: it starts from the concrete v5.5/v5.6 runtime and describes what
changes in v6.0. It should not be read as permission to rewrite current-state docs as if the target
already exists.

Read this together with:
- `docs/DESIGN_PRINCIPLES.md` for stable design rules,
- `docs/ROADMAP.md` for phase sequencing,
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` for capability and agent evolution,
- `docs/FINDING_AND_REORIENTING/README.md` for retrieval/orientation/resurfacing separation,
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` for interaction-surface authority,
- `docs/COMMITMENT_AS_FIRST_CLASS/README.md` for commitment semantics.

## What v6.0 Inherits From v5.5/v5.6

The current baseline is not an abstract pre-runtime. v6.0 inherits a working local-first runtime:

- **Vault-first human surface**: Obsidian vault notes remain the primary human writing and reading surface.
- **Registry watcher runtime ingress**: the registry watcher is the runtime default; legacy snapshot watchers are dev-only.
- **DB outbox canonical runtime queue**: Postgres outbox is the canonical queue for runtime side effects; JSONL is audit/diagnostic only.
- **Portable continuity set**: vault note plus companion note form the portable continuity and repair set.
- **Rebuildable derived state**: runtime DB/index state is rebuildable from the portable file-based set.
- **Guarded mutation path**: PanelAgent, watcher policy, idempotency, optimistic writes, note writer boundaries, and status/health surfaces already provide controlled mutation scaffolding.
- **Capability seams already started**: `ReasoningFacade`, LangGraph graph seams, Orchestrator V2 flagging, A2A/MCP contracts, and settings compiler provenance exist, but their current rollout status is mixed and must not be overstated.

Baseline rule:
- v6.0 should preserve the current safety properties while clarifying boundaries.
- v6.0 should not re-center the architecture on a DB-primary model, ASK, a single agent, or a purely abstract ontology diagram.

## What Actually Changes In v6.0

v6.0 changes the operating model, not the fact that the system is local-first and vault-centered.

The intended changes are:
- make the execution boundary explicit: `observation -> normalization/contract -> admission -> execution`;
- separate human, replication, observation, contract, execution, and derived-machine layers;
- treat retrieval, orientation, and resurfacing as separate capabilities instead of one blended ASK/retrieval concern;
- distinguish capabilities, orchestrators/bounded agents, pipelines, and execution substrate;
- make surface authority explicit for writing, retention, system support, runtime views, and execution records;
- treat domain/zone/mirror/promotion problems as current-state fixes or enabling changes unless and until a target-state implementation lands;
- stage migration for retrieval, multi-device/replica posture, and interaction/cognition/governance/execution separation.

Non-change:
- v6.0 does not make Chat mutation-capable by default.
- v6.0 does not make Deep Agents production mutation actors.
- v6.0 does not make derived runtime DB/index state semantically primary.
- v6.0 does not mean relation-aware retrieval, commitment runtime, or replica-aware operation are already implemented.

## Operating Layers

Use these layers when reviewing target-state architecture.

| Layer | Role | Current baseline | v6.0 target change |
| --- | --- | --- | --- |
| Human canonical layer | Human-authored meaning-bearing artifacts | Vault notes are canonical human writing/reading surface | Keep vault-first; make artifact authority explicit and avoid making runtime projections the hidden truth |
| Replication layer | Portable continuity and multi-device convergence | Vault note + companion note provide portable continuity; sync transport is operational, not semantic | Model instance/replica posture, lag, partial views, and rebuild as normal operating conditions |
| Observation layer | Detect changed material or human/runtime signals | Registry watcher is runtime ingress; Panel/CLI/API emit intents/events | Keep observation read/emit-oriented; do not execute directly from observation |
| Normalization/contract layer | Convert observations into typed, validated runtime contracts | Settings compiler, event envelope, panel action catalog, note writer policy, A2A/MCP contracts exist | Make normalization explicit before admission: scope, provenance, consent/approval, idempotency, and surface authority must be checked here |
| Execution layer | Apply admitted actions through controlled mechanisms | DB outbox, worker, promotion consumer, panel runtime, CLI-first orchestrator paths | Keep execution downstream of admission; allow orchestrators to coordinate only through governed actions |
| Derived machine layer | Runtime DB/index/search projections, status, traces, metrics | Store projections, chunks, embeddings, hybrid retrieval, status/health | Keep rebuildable; expose provenance and explanation without granting canonical meaning authority |

Layering rule:
- a user edit belongs first to the human canonical layer;
- a companion note belongs to the replication/system continuity part of the file-based continuity set;
- watcher observations do not equal admission;
- DB outbox work does not equal semantic approval;
- indexes and retrieval documents are derived machine views, not canonical artifacts.

## Execution Boundary

All mutation-capable or automation-capable paths should be described through this boundary:

`observation -> normalization/contract -> admission -> execution`

| Stage | What it does | Examples | Must not do |
| --- | --- | --- | --- |
| Observation | Detects changed notes, panel content, CLI/API requests, or runtime signals | registry watcher event, panel scan, status signal, API request | Mutate durable state merely because something was observed |
| Normalization/contract | Parses and converts inputs into typed contracts with provenance | panel action intent, event envelope, tool descriptor, settings compiler output, retrieval projection metadata | Treat ambiguous input as execution-ready |
| Admission | Decides whether the contracted action may run now | allowlist, write guard, checkbox consent, policy gate, idempotency/dedup, approval/admissibility check | Hide policy failure by silently executing or dropping accountability |
| Execution | Performs the admitted side effect through controlled substrate | DB outbox worker, note writer, promotion consumer, orchestrator executor, MCP/tool adapter | Bypass provenance, receipts, idempotency, or surface authority |

Target-state rule:
- cognition can assist observation, normalization, and proposal generation;
- cognition must not collapse admission and execution;
- execution records must remain traceable back to the observation and contract that admitted them.

## Surface Authority Matrix

| Surface | What it is authoritative for | Current baseline | v6.0 target posture | Not authoritative for |
| --- | --- | --- | --- | --- |
| Writing surface | Human-authored, editable primary artifacts | Obsidian vault notes | Remains human canonical layer | Runtime queue state, system traces, derived ranking truth |
| Retention surface | Source-rich retained material for citation, rediscovery, and reuse | Conceptually defined; not a broad runtime surface yet | Stage as a distinct retained-material layer without collapsing it into notes or DB projections | Human-authored note state or execution approval |
| System surface | Continuity, mirrors, receipts, operational traces, indexes/projections as support structures | Companion notes are first-class continuity artifacts; mirror/receipt distinctions remain transitional in places | Split mirror, receipt, operational trace, and projection roles clearly | Sole semantic truth for human artifacts |
| Runtime surface | Store rows, outbox rows, worker state, status/health, runtime projections | DB outbox canonical queue; store/index projections support current runtime | Keep operationally authoritative for runtime coordination | Human artifact meaning or long-term retention semantics |
| Execution records | Evidence that an admitted action ran or failed | Events, receipts, status callouts, worker logs, promotion events | Make records link observation, contract, admission, executor, and durable effect | Substitute for human-legible accountability or artifact content |

Surface rule:
- the writing surface carries human-authored meaning;
- the retention surface preserves source-rich material;
- the system surface carries continuity and accountability support;
- the runtime surface coordinates local operation;
- execution records prove governed action, not artifact meaning.

## Capabilities, Agents, Pipelines, and Substrate

v6.0 should stop using "agent" as the default name for every reusable function.

| Term | Definition | Examples | Target-state rule |
| --- | --- | --- | --- |
| Capability | A reusable function with a contract, inputs, outputs, and policy expectations | retrieve, rerank, context build, orientation support, resurfacing support, reasoning support, transformation | Capabilities are callable building blocks; they do not own broad authority by themselves |
| Orchestrator / bounded agent | A bounded coordinator or decision-maker with an explicit role and authority | PanelAgent, planned read-only Chat cognition, planner, reviewer/hygiene-style bounded agents, Orchestrator V2 pilot | May select or coordinate capabilities, but must respect admission and execution boundaries |
| Pipeline | Deterministic or semi-deterministic staged processing path | ingest -> store -> outbox -> worker -> index; panel parse -> action intent -> event; retrieval query -> candidate search -> optional rerank | Valid when it is clearer and safer than richer agent behavior |
| Execution substrate | The mechanism that performs admitted side effects | DB outbox worker, note writer, CLI orchestrator executor, MCP/tool adapter, future sandboxed executor | Must be governed, idempotent, observable, and receipt-bearing |

Design consequence:
- retrieval should become a capability used by Panel, Chat, ASK compatibility, orientation, and resurfacing paths;
- Panel remains the current mutation-capable interaction surface, not proof that all future cognition is a PanelAgent responsibility;
- Chat can become a canvas-shaped interaction surface later, but early Deep Agent work remains read-only;
- execution substrate evolves only after governance and admission contracts are explicit.

## Current Findings Classification

The following known findings are not already solved v6 reality.

### Current-state bug fixes

These violate accepted current contracts or make current behavior misleading:

- **Finding 1: Domain inferred from path fallback**: path-derived domain fallback should be removed or made conservative because folder placement must not silently become semantic scope.
- **Finding 2: Zone read as stored payload truth**: `zone` should not be read as if it were canonical artifact state; zone/salience are derived overlays.
- **Finding 3: Missing domain/scope write-boundary handling**: missing scope should become explicit/conservative rather than implicit permissive behavior.

These can land before v6.0 as current-state corrections if the owning docs and tests stay aligned.

### Enabling changes

These prepare v6 without claiming it exists:

- **Finding 4: Mirror conflates artifact identity with audit log**: split identity/portability mirror responsibilities from audit/accountability receipts where current support surfaces are still conflated.
- **Finding 5: Promotion mutates artifact state without a clear transition record**: keep existing promotion mutation compatibility, but add clear transition receipts so authorization and effect are inspectable.
- **Relation-store enablement**: additive sphere/context/relation support may prepare relation-aware retrieval while current retrieval defaults remain conservative.
- **Settings and contract provenance**: continue making compiler outputs, action catalogs, and tool descriptors explainable before they are used for admission.

### v6.0 target-state changes

These require target-state sequencing and must not be described as current runtime:

- **Finding 6: Single `domain` field represents all of human context**: replace flat domain/context semantics with layered operational scope, spheres, situated role identity, contexts, and shared participation;
- **Finding 7: `kind` is hardcoded to `note` for all ingested artifacts**: introduce artifact-kind and policy routing at ingest/normalization boundaries without claiming that routing exists today;
- make retrieval relation/provenance-aware while preserving conservative defaults and explainability;
- separate orientation and resurfacing from retrieval;
- introduce a clearer retained-material surface;
- mature Chat/cognition separation without widening mutation authority prematurely;
- normalize multi-device and replica-aware operation as an architecture property.

## Staged Migration

### Retrieval migration

Current baseline:
- `docs/RETRIEVAL.md` describes in-process hybrid search, optional rerank, operational-scope filters, path/source hints, and retrieval metadata.
- ASK remains a valid compatibility surface but is deprecated as architecture center.

Stages:
1. **Current-state correction**: make missing scope/domain behavior conservative and remove accidental path-as-domain authority.
2. **Capability extraction**: expose retrieval as `retrieve` / `rerank` / `context_build` capability contracts usable by multiple surfaces.
3. **Signal layering**: add explicit provenance, relation, retained-material, and overlap signals as bounded retrieval inputs.
4. **Separation**: split retrieval, orientation, and resurfacing flows so ranking explanations do not masquerade as orientation or salience.
5. **Acceptance**: prove behavior with current retrieval tests plus scenario-level validation from `docs/FINDING_AND_REORIENTING/`.

### Multi-device / replica migration

Current baseline:
- vault note + companion note are the portable continuity set;
- runtime DB/index state is rebuildable;
- iCloud/Git-like sync transport is operational plumbing, not semantic authority;
- instance settings exist, but broad replica semantics are not a full runtime model yet.

Stages:
1. **Preserve continuity set**: keep vault and companion artifacts portable and human-inspectable.
2. **Record instance provenance**: make instance/device/runtime provenance explicit on runtime records without changing artifact identity.
3. **Handle lag explicitly**: retrieval, ingest, and execution should report stale/partial views instead of assuming a globally fresh runtime.
4. **Rebuild discipline**: make derived DB/index rebuild paths ordinary operating procedures, not disaster-only behavior.
5. **Replica posture**: define which replicas may observe, normalize, admit, and execute; do not let every replica imply full execution authority.

### Interaction / cognition / governance / execution separation

Current baseline:
- Panel is the current mutation-capable interaction surface.
- Chat and Deep Agents are target-state/future work.
- Planner/orchestrator paths exist, but broad execution expansion remains gated.

Stages:
1. **Panel as baseline**: keep Panel mutation paths stable and governed.
2. **Capability contracts**: make retrieval/reasoning/transformation/context-building capabilities callable without granting execution authority.
3. **Read-only cognition slice**: introduce richer Chat/Deep Agent cognition only in read-only mode first.
4. **Admission contracts**: define shared admissibility checks for approvals, policy, idempotency, write guard, and surface authority.
5. **Execution substrate expansion**: only after admission is explicit, add broader executors or tool adapters with sandboxing, receipts, and rollback posture.

## Non-goals

This target model does not define:
- a concrete DB schema,
- a concrete graph schema,
- exact event payload redesigns,
- a full service decomposition,
- a complete retained-material implementation,
- or a production-ready Deep Agent execution system.

Those belong to downstream implementation slices after this operating model is accepted.

## Exit Condition

This target model is actionable when planned work can be classified cleanly as:
- current-state bug fix,
- enabling change,
- or v6.0 target-state change,

and when each proposed slice states:
- which operating layer it changes,
- which surface has authority,
- which boundary stage it affects,
- which current baseline behavior it preserves,
- and what would prove it is implemented rather than merely described.

---

## Related Documents

- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/ROADMAP.md`
- `docs/RETRIEVAL.md`
- `docs/PANEL_AGENT.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/ONTOLOGY_RUNTIME_BRIDGE.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
