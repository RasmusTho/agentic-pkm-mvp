State: SBS initiative roadmap; phase intent and status for operationalizing the target SBS. Target-state process surface, not a shipped-runtime claim.
Doc role: Initiative roadmap / phase model
Authority: Owns the phase framing and status of the SBS operationalization initiative. Subordinate to `docs/ROADMAP.md` on overall strategic sequencing and to `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` on contract-first slice ordering. Does not own the decomposition (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`) or shipped reality (`docs/STATUS.md`).
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc for SBS phase intent/status; GitHub issues for executable work
Last reviewed: 2026-06-21
Last verified against: docs/ROADMAP.md, docs/architecture/SBS_OPERATIONALIZATION_PLAN.md, docs/architecture/SBS_OPERATING_MODEL.md, docs/architecture/SBS_BOUNDARY_REGISTER.md, GitHub issues #2337 #2355 #2356-#2363 #2371 #2374 #2375 #2376

# SBS Roadmap

This roadmap expresses the SBS operationalization initiative as phases with operational intent, not just an issue list. It is the "where are we and why" view that complements `docs/ROADMAP.md` (overall sequencing) and `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` (contract-first slice ordering).

It is **not** a commitment to build fourteen modules. Phases 1–4 add *seams* (adapters and contracts) over current implementation; Phase 5 splits modules only where evidence justifies it (ADR-0016).

## Status vocabulary

- **Done** — artifacts resident and/or first seam delivered; the phase's enabling intent is in place.
- **In progress** — some artifacts/slices delivered, others open.
- **Planned** — intent defined, no slice delivered.
- **Deferred** — deliberately not started; waiting on evidence or an earlier phase.

## Phase summary

| Phase | Theme | Status | Primary subsystems |
|---|---|---|---|
| Phase 0 | Architecture residency | Done (operating layer landing in this PR) | CES practice, all (documentation) |
| Phase 1 | Control-plane seams | In progress (first seams delivered) | WSP, GOV |
| Phase 2 | First enforcement rails | In progress (first rail shipped) | OEF |
| Phase 3 | Cognitive seams | Planned | RCA, MEM, CAO |
| Phase 4 | Execution and federation seams | Planned | EXE, SFC, PDM, EBF |
| Phase 5 | Opportunistic physical separation | Deferred | per evidence |

## Phase 0 — Architecture residency

**Purpose.** Make the target SBS official, resident, and operable from the repository alone, so no SBS decision lives only in a conversation.

**Key artifacts.** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`; ADR-0015–ADR-0019; `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`, `SBS_CURRENT_TO_TARGET_MAPPING.md`, `SBS_BOUNDARY_REGISTER.md`, `SBS_TRANSITION_DEBT.md`, `SBS_FITNESS_RULES.md`; the ten critical contract stubs in `docs/contracts/`; SBS impact sections in the issue and PR templates; and — landing in this initiative — `docs/architecture/SBS_OPERATING_MODEL.md` and this roadmap, plus the review-gate fallback policy and source-of-truth matrix.

**Relevant issues.** Tracking `#2337`; operationalization issues `#2338`–`#2354`; the operating-model umbrella issue (this PR's contract).

**Current status.** Done for the strategy/contract layer. The operating-model layer (operating model, roadmap, hardened debt register, prioritized fitness roadmap, review-gate fallback policy, template field completion, source-of-truth matrix) lands with this initiative, completing residency.

**Blockers.** None.

**Non-goals.** No module creation; no claim that any contract is enforced in code merely by being documented.

## Phase 1 — Control-plane seams

**Purpose.** Introduce the WSP (context) and GOV (authority) control-plane seams so active-context binding and authority-bearing writes stop being implicit. These are the seams that govern everything downstream, so they come first.

**Key artifacts.** `docs/contracts/ACTIVE_CONTEXT_SET.md` (WSP); `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` + ADR-0019 (GOV); the `ActiveContextResolver` adapter and the `GovernedWriteAdapter` over the representative capture path.

**Relevant issues.** `#2356` ActiveContextResolver (closed); `#2357` governed-write adapter (closed, PR `#2371` merged); `#2375` owner-doc writeback for governed-capture acknowledgement (open — Phase 1 owner-doc debt).

**Current status.** In progress. The first WSP and GOV seams are delivered around narrow paths; broad adoption across all write paths remains. Owner-doc writeback for the acknowledgement behavior change is tracked by `#2375`.

**Blockers.** `#2375` must close to keep Phase 1 owner docs truthful.

**Non-goals.** Do not remove vault support; do not route every write through GOV in one slice; widen seam-by-seam.

## Phase 2 — First enforcement rails

**Purpose.** Make at least one architecture violation mechanically visible, turning the fitness rules from documentation into enforcement and proving the OEF rail pattern.

**Key artifacts.** `tests/architecture/test_sbs_fitness_rules.py::test_target_sbs_contracts_do_not_reintroduce_active_vault_identity`; the enforcement-posture classification and the prioritized P0/P1/P2 rule roadmap in `docs/architecture/SBS_FITNESS_RULES.md`.

**Relevant issues.** `#2363` first mechanical SBS fitness checks (closed, PR `#2376` merged); follow-up to convert remaining P0 manual rules into CI checks (filed in this initiative).

**Current status.** In progress. The first rail (no reintroduced `activeVault`/`vaultPath` in target contracts outside WSP) ships and runs read-only in CI. The remaining P0 rules (governed-write enforcement, no direct HKA mutation from non-owners) are manual-review-now pending code shape and are queued for CI promotion.

**Blockers.** Governed-write CI enforcement depends on `DecisionToken`/`AuthorityReceipt` existing in code on enough paths (Phase 1 widening).

**Non-goals.** Do not mark a rule "CI check now" without a real test; do not let OEF mutate runtime behavior — it reports and blocks CI only.

## Phase 3 — Cognitive seams

**Purpose.** Seam the Cognitive Augmentation subsystems (RCA retrieval, MEM memory, CAO orchestration) so retrieval output is candidate-only, memory carries review/provenance, and agents cannot silently absorb adjacent authority.

**Key artifacts.** `docs/contracts/CONTEXT_BUNDLE.md` (RCA), `docs/contracts/MEMORY_RECORD.md` (MEM), `docs/contracts/CAPABILITY_CONTRACT.md` + `docs/contracts/WORKFLOW_CONTRACT.md` (CAO); ContextBundle conformance over retrieval outputs; a MemoryRecord adapter over the current memory lifecycle.

**Relevant issues.** `#2359` ContextBundle conformance check (open); `#2360` MemoryRecord adapter (open).

**Current status.** Planned. Contracts are resident; adapters/conformance not yet delivered. Transition-debt rows for "retrieval not formalized as ContextBundle" and "memory lacking review/provenance lifecycle" stay open until these land.

**Blockers.** Benefits from a stable WSP scope seam (Phase 1) for ContextBundle scope fields.

**Non-goals.** Do not let RCA write HKA; do not let unreviewed MEM become hidden instruction; do not let CAO call tools directly (that is EXE/GOV, Phase 4).

## Phase 4 — Execution and federation seams

**Purpose.** Seam the side-effect and distribution boundaries: EXE (governed execution), SFC (sync/federation), with PDM (persistence) and EBF (external boundary) as the substrate they depend on. This is where agents' effects become governed and where the single-node posture is named before federation exists.

**Key artifacts.** `docs/contracts/EXECUTION_REQUEST.md` (EXE), `docs/contracts/REPLICATION_ENVELOPE.md` (SFC), `docs/contracts/STORE_PORT.md` (PDM); an ExecutionRequest wrapper around one side-effect path; a SourceObservationEvent/ReplicationEnvelope adapter for watcher/sync events; a StorePort wrap of the first persistence seam.

**Relevant issues.** `#2361` ExecutionRequest wrapper (open); `#2362` SourceObservationEvent/ReplicationEnvelope adapter (open); `#2358` first StorePort persistence seam (open).

**Current status.** Planned. Contracts resident; no adapters delivered. StorePort underpins earlier phases too but is sequenced here because direct persistence use is widespread and wrapping it is a larger inventory job.

**Blockers.** ExecutionRequest depends on the GOV DecisionToken seam (Phase 1) so execution can reference an authorization.

**Non-goals.** Do not build distributed consensus; SFC stays no-op/single-node. Do not let SFC resolve semantic conflicts (that routes through GOV/HIX).

## Phase 5 — Opportunistic physical separation

**Purpose.** Physically split a conceptual subsystem into its own module/service/package **only** when evidence justifies it — a second independent volatility clock, a failure-mode boundary, an authority/deployment posture, repeated boundary violations, or a failed replacement exercise (ADR-0016).

**Key artifacts.** Candidate split proposals (as ADRs) for the subsystems most likely to justify separation first: GOV, WSP, PDM, RCA, MEM, EXE, SFC.

**Relevant issues.** None yet; a split is filed as its own ADR + issue when its trigger fires.

**Current status.** Deferred by design. No split is justified yet; the contract-first/module-lazy posture (ADR-0016) governs.

**Blockers.** Requires accumulated evidence from Phases 1–4 plus a concrete volatility/failure trigger.

**Non-goals.** Do not pre-split for symmetry or to "match the SBS"; the SBS is a control-boundary map, not a package map.

## Delivery-slice to phase mapping

Delivery slices `#2356`–`#2363` (under delivery parent `#2355`, tracked by `#2337`) do not map one-to-one onto these phases; the operationalization plan owns their contract-first order. This table reconciles the two views:

| Slice | Subsystem | Initiative phase | State |
|---|---|---|---|
| #2356 ActiveContextResolver | WSP | Phase 1 | Closed |
| #2357 governed-write adapter | GOV | Phase 1 | Closed (PR #2371) |
| #2363 first fitness checks | OEF | Phase 2 | Closed (PR #2376) |
| #2359 ContextBundle conformance | RCA | Phase 3 | Open |
| #2360 MemoryRecord adapter | MEM | Phase 3 | Open |
| #2361 ExecutionRequest wrapper | EXE | Phase 4 | Open |
| #2362 SourceObservationEvent/ReplicationEnvelope | SFC/EBF | Phase 4 | Open |
| #2358 StorePort seam | PDM | Phase 4 | Open |

## Reconciliation with the operationalization plan

`docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` defines a six-phase *adoption* sequence (decision anchoring → current-to-target mapping → critical contracts → first enforcement rails → containment adapters → selective physical split). This roadmap re-cuts the same work into *initiative* phases oriented around which control boundaries are seamed when. Both are consistent: the operationalization plan owns contract-first slice ordering; this roadmap owns phase intent and status. Where they refer to the same artifact, the artifact's own doc header is authoritative.
