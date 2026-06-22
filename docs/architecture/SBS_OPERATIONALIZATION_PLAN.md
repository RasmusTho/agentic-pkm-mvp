State: Target-state architecture operationalization plan; docs/contracts/issues resident; implementation in progress and not claimed as shipped.
Doc role: Plan / operationalization control surface
Authority: Owns how the target SBS becomes operational through contracts, mappings, registers, fitness rules, roadmap entries, and issues. The canonical target SBS remains `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`; current runtime behavior remains owned by `docs/ARCHITECTURE.md` and `docs/STATUS.md`.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/ROADMAP.md

# SBS Operationalization Plan

This plan turns the target System Breakdown Structure into working repository practice without a big-bang rewrite.

## Purpose

- Make the target SBS discoverable, durable, actionable, and connected to current architecture work.
- Stabilize contracts before physical module splits.
- Give future changes a way to declare SBS impact.
- Track transition debt honestly without claiming the runtime already implements the target.

## Non-goals

- Do not create fourteen new physical modules immediately.
- Do not rewrite the system to no-vault now.
- Do not remove Obsidian now.
- Do not build full distributed consensus now.
- Do not make GOV a general mechanism god-core.
- Do not let OEF become an automatic control loop.
- Do not claim target-state architecture as shipped behavior.
- Do not reorganize the repository solely to mirror the SBS.
- Do not treat this as an implementation refactor before docs, contracts, and issues are resident.

## Adoption Principle

Adopt the target SBS contract-first and module-lazy.

All target boundaries are declared now as charters, contracts, dependency rules, registers, and fitness expectations. A conceptual boundary becomes a separate physical module/service only when justified by volatility, ownership, failure mode, authority posture, deployment posture, storage lifecycle, repeated boundary violations, or failed replacement exercises.

## Source-Of-Truth Matrix

| Concern | Source of truth | Notes |
|---|---|---|
| Target SBS decomposition | `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` | Owns long-horizon subsystem boundaries. |
| Current runtime architecture | `docs/ARCHITECTURE.md` | Owns shipped/current behavior. |
| Current system-of-systems spine | `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` | Owns current SoS framing. |
| SBS operationalization | `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` | Owns transition from strategy to operational reality. |
| SBS operating model (process) | `docs/architecture/SBS_OPERATING_MODEL.md` | Owns how SBS work is classified, readied, done, reviewed, and recorded; review-gate fallback policy; source-of-truth verification matrix. |
| SBS roadmap (initiative phases) | `docs/architecture/SBS_ROADMAP.md` | Owns phase intent and status (Phase 0 architecture residency → Phase 5 opportunistic physical separation). |
| Current-to-target mapping | `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` | Owns mapping between existing docs/code concepts and target SBS. |
| Boundary status | `docs/architecture/SBS_BOUNDARY_REGISTER.md` | Owns boundary existence/enforcement status. |
| Transition debt | `docs/architecture/SBS_TRANSITION_DEBT.md` | Owns known deviations from target architecture. |
| Fitness rules | `docs/architecture/SBS_FITNESS_RULES.md` | Owns architecture enforcement rules. |
| Critical contracts | `docs/contracts/*.md` | Owns contract definitions. |
| Roadmap | `docs/ROADMAP.md` | Owns strategic sequencing and initiative status. |
| Issues | GitHub issues created from this plan | Own executable work items. |
| ADRs | `docs/adr/*` | Own durable architecture decisions. |
| Builder System boundary | `docs/architecture/SBS_OPERATING_MODEL.md` §3 | Owns the continuous-development enabling system boundary, including how Builder System work relates to Product/Runtime SBS and CES. |

## Phase Plan

| Phase | Purpose | Deliverables | Definition of done |
|---|---|---|---|
| Phase 0 - Decision anchoring | Make the target SBS official. | Target SBS document, ADRs, roadmap entry, tracking issue. | The target SBS is documented, explicitly target-state, and referenceable by future architecture decisions. |
| Phase 1 - Current-to-target mapping | Orient the operational reality. | Current-to-target mapping, boundary register, transition debt register, initial change-impact model. | Each current architectural concern has a target owner; major leaks are named without requiring immediate repair. |
| Phase 2 - Critical contracts | Introduce stable seams without big-bang refactor. | ActiveContextSet, GovernedWriteProtocol, ArtifactContract, StorePort, ContextBundle, MemoryRecord, ExecutionRequest, ReplicationEnvelope. | Each contract has owner, invariants, allowed/forbidden use, and transitional implementation mapping. |
| Phase 3 - First enforcement rails | Make architecture violations visible. | OEF/CI fitness rules, grep/lint checks where easy, manual review rules where automation is premature. | At least some violations are mechanically visible and new major work declares SBS impact. |
| Phase 4 - Containment adapters | Encapsulate current implementation without total rewrite. | ActiveContextResolver, StorePort adapter, ContextBundle adapter, MemoryRecord adapter, ExecutionRequest adapter, SourceObservationEvent/ReplicationEnvelope adapters. | New code uses seams while old code can be adapted gradually. |
| Phase 5 - Selective physical split | Physically separate only where justified. | Candidate splits for GOV, WSP, PDM, RCA, MEM, EXE, SFC. | Physical split happens only when enforcement or volatility requires it. |

## Critical Contracts

| Contract | Owner | Path | First slice |
|---|---|---|---|
| ActiveContextSet | WSP | `docs/contracts/ACTIVE_CONTEXT_SET.md` | Slice 1 |
| GovernedWriteProtocol | GOV | `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` | Slice 2 |
| ArtifactContract | HKA | `docs/contracts/ARTIFACT_CONTRACT.md` | Slice 3 |
| StorePort | PDM | `docs/contracts/STORE_PORT.md` | Slice 4 |
| ContextBundle | RCA | `docs/contracts/CONTEXT_BUNDLE.md` | Slice 5 |
| MemoryRecord | MEM | `docs/contracts/MEMORY_RECORD.md` | Slice 6 |
| ExecutionRequest | EXE | `docs/contracts/EXECUTION_REQUEST.md` | Slice 7 |
| ReplicationEnvelope | SFC | `docs/contracts/REPLICATION_ENVELOPE.md` | Slice 8 |
| CapabilityContract | CAO | `docs/contracts/CAPABILITY_CONTRACT.md` | Phase 2 support |
| WorkflowContract | CAO | `docs/contracts/WORKFLOW_CONTRACT.md` | Phase 2 support |

## First Implementation Slices

| Slice | Owner | Purpose | Acceptance summary |
|---|---|---|---|
| Slice 1 - ActiveContextSet | WSP | Stop active vault from being the global architecture primitive. | Contract supports zero/one/many bindings, workspace, scope, sphere, situated identity, principal context, topology posture, generation/version, and transitional vault/source binding. |
| Slice 2 - GovernedWriteProtocol | GOV | Make authority-bearing durable writes executable and auditable. | PolicyDecision, DecisionToken, AuthorityReceipt, write classes, pre-mutation validation, post-mutation receipt, and transitional enforcement are defined. |
| Slice 3 - ArtifactContract | HKA | Protect human knowledge survivability. | Artifact-origin facts, portable representation, ownership markers, derived semantic boundary, and survival invariant are explicit. |
| Slice 4 - StorePort | PDM | Stop storage technology from becoming architecture. | Store resolution, no private DSN/store construction, durable/rebuildable classes, and migration responsibility are defined. |
| Slice 5 - ContextBundle | RCA | Prevent retrieval from becoming truth. | Scope, provenance, evidence references, ranking/relevance explanation, staleness/uncertainty, and non-authority invariant are explicit. |
| Slice 6 - MemoryRecord | MEM | Prevent memory from becoming hidden instruction. | Memory classes, review state, provenance, confidence, staleness, correction, forgetting, and GOV promotion path are defined. |
| Slice 7 - ExecutionRequest | EXE | Separate agents from side-effecting execution. | DecisionToken reference, dry-run/preview/rollback posture, execution result, and receipt/trace linkage are defined. |
| Slice 8 - ReplicationEnvelope | SFC | Name the distribution seam before central/satellite is implemented. | Single-node/no-op posture, node/replica identity, delivery, idempotency, replay/backfill, conflict envelope, and upgrade path are defined. |

## Operational References

- Operating model (how to use the SBS day-to-day): `docs/architecture/SBS_OPERATING_MODEL.md`
- Initiative roadmap (phase intent and status): `docs/architecture/SBS_ROADMAP.md`
- Current-to-target mapping: `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`
- Boundary register: `docs/architecture/SBS_BOUNDARY_REGISTER.md`
- Transition debt: `docs/architecture/SBS_TRANSITION_DEBT.md`
- Fitness rules: `docs/architecture/SBS_FITNESS_RULES.md`
- Target SBS: `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- Current SoS bridge: `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`

## Definition Of Done

- Target SBS is canonical and discoverable.
- Operationalization plan, mapping, boundary register, transition debt register, and fitness rules exist.
- Critical contract stubs exist.
- ADRs exist for the settled SBS decisions.
- Roadmap/status/index/reading paths distinguish target state from shipped runtime.
- PR process includes SBS impact classification.
- GitHub issues track the executable work.
- No future action required by this plan lives only in a prompt or final response.

## Issue Tracking

Tracking issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/2337

| Issue | Scope |
|---|---|
| #2338 | Adopt Target SBS as strategic architecture reference. |
| #2339 | Create SBS Operationalization Plan. |
| #2340 | Create Current-to-Target SBS Mapping. |
| #2341 | Create SBS Boundary Register. |
| #2342 | Create SBS Transition Debt Register. |
| #2343 | Define ActiveContextSet contract. |
| #2344 | Define GovernedWriteProtocol with DecisionToken and AuthorityReceipt. |
| #2345 | Define ArtifactContract survivability rules. |
| #2346 | Define StorePort / PDM persistence resolution contract. |
| #2347 | Define ContextBundle contract. |
| #2348 | Define MemoryRecord lifecycle contract. |
| #2349 | Define ExecutionRequest seam between CAO/GOV/EXE. |
| #2350 | Define ReplicationEnvelope and SFC single-node posture. |
| #2351 | Create first SBS fitness rules in OEF/CI. |
| #2352 | Add SBS impact classification to PR / initiative templates. |
| #2353 | Add architecture roadmap entry for SBS operationalization. |
| #2354 | Add ADRs for SBS settlement decisions. |

## Delivery Issue Set

Delivery parent issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/2355

| Issue | Delivery slice |
|---|---|
| #2356 | Introduce ActiveContextResolver around active vault. |
| #2357 | Add governed-write adapter for DecisionToken and AuthorityReceipt. |
| #2358 | Inventory and wrap first StorePort persistence seam. |
| #2359 | Add ContextBundle conformance check for retrieval outputs. |
| #2360 | Wrap current memory lifecycle in MemoryRecord adapter. |
| #2361 | Introduce ExecutionRequest wrapper for one side-effect path. |
| #2362 | Add SourceObservationEvent or ReplicationEnvelope adapter for watcher/sync events. |
| #2363 | Implement first mechanical SBS fitness checks. |
