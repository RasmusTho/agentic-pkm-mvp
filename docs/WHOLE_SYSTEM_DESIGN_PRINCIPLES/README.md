State: Accepted target-state capability specification; no runtime or Builder enforcement is shipped by this document. Shared validation epic: pending filing.
Doc role: Capability specification
Authority: Defines the bounded delivery needed to make existing whole-system principles selectable and enforceable without transferring their ownership to Builder System.
Owner: Architecture / CES, with local Product, Builder, and Platform/Ops owner contracts retaining their authority.
Temporal class: Target-state specification
Review cadence: At each child delivery and before parent acceptance.
Source of truth: `docs/DESIGN_PRINCIPLES.md` remains canonical for stable principles; this directory owns only delivery decomposition and acceptance.

# Whole-System Design Principle Routing

## Capability Boundary

Yggdrasil already has stable principles, architecture owners, an invariant registry, and narrow
workflow skills. This capability makes those authorities usable as a small change-specific design
packet. A deterministic resolver selects exact principle IDs, owner sections, and applicable
fitness evidence from declared change facts. Product/Runtime, Builder System, and Platform/Ops
continue to own their local contracts; the resolver and its packets are projections, not a new
architecture authority.

The boundary also makes one architectural rule explicit: a capability that performs durable or
external effects crosses a named owner port. A pure internal function is not wrapped merely to
increase abstraction. The rule prevents both hidden effect authority and generic-wrapper sprawl.

## Cross-Task Invariants / Interaction Safety

1. **Canonical authority stays put.** Stable principle text remains in `docs/DESIGN_PRINCIPLES.md`;
   local owner contracts retain detailed semantics and current-state truth.
2. **Packets are deterministic projections.** Equal normalized change facts and repository head
   produce equal ordered selections with source references; packets never become accepted truth.
3. **Read only what applies.** Routing selects the smallest sufficient principle and owner sections;
   it never requires blanket loading of the documentation corpus.
4. **Effects use owned ports.** Durable or external effects have a named owner contract and port.
   Pure internal computation needs no generic wrapper.
5. **Ambiguity fails loud.** Unknown authority, missing owner references, conflicting rules, or stale
   routing metadata produce typed refusal instead of a guessed packet.
6. **One enforcement registry.** `docs/testing/invariant-tests.md` and
   `docs/architecture/SBS_FITNESS_RULES.md` remain the enforcement owners; no parallel registry is
   introduced.
7. **Truth classes remain separate.** Target-state specifications, current runtime truth, Builder
   workflow policy, and operational evidence are never collapsed into one document or result.

## Implementation Tasks And Execution Order

1. [Establish the Principle Kernel](ESTABLISH_PRINCIPLE_KERNEL.md) — DSP-01. Assign stable IDs and
   selection metadata to the existing canonical principles and their compact projections.
2. [Resolve Minimal Design Packets](RESOLVE_MINIMAL_DESIGN_PACKETS.md) — DSP-02. Depends on DSP-01;
   implement deterministic, read-only selection and typed refusal.
3. [Route Builder Reading](ROUTE_BUILDER_READING.md) — DSP-03. Depends on DSP-02; connect the
   resolver to repo workflow routing without moving system authority into Builder instructions.
4. [Enforce Owned Effect Boundaries](ENFORCE_OWNED_EFFECT_BOUNDARIES.md) — DSP-04. Depends on
   DSP-01; extend the existing fitness registry for owned ports and anti-wrapper scope.
5. [Report Design Boundary Drift](REPORT_DESIGN_BOUNDARY_DRIFT.md) — DSP-05. Depends on DSP-02 and
   DSP-04; add a read-only doctor and integrated drift report.

Delivery is serial by default. A later issue is filed only when all declared prerequisites are live
and its issue body can be strict-ready without inferring dependency completion.

## Capability Acceptance

- [ ] DSP-01 through DSP-05 are terminally delivered with exact-head evidence and parent receipts.
- [ ] A representative Product, Builder, Platform/Ops, and boundary change each resolves to the
  smallest sufficient packet, while ambiguous input refuses.
- [ ] Fitness evidence proves new durable/external effects cross an owned port and that pure internal
  functions are not required to acquire wrappers.
- [ ] The read-only doctor detects stale IDs, missing owner references, duplicate rule ownership,
  unclassified effects, and packet drift without mutating repo or GitHub state.
- [ ] Owner-doc review confirms that no current-state or shipped-capability claim was promoted merely
  because the routing capability exists.

## Reconciliation — Do Not Duplicate

- `docs/DESIGN_PRINCIPLES.md` owns principle text; this specification must amend, not replace, it.
- `docs/PROJECT_KERNEL.md` owns the product stability subset.
- `docs/MODULAR_ARCHITECTURE.md` owns the structural projection.
- `docs/testing/invariant-tests.md` and `docs/architecture/SBS_FITNESS_RULES.md` own enforcement
  inventory and posture.
- Issue #3957 remains the separate current-state `docs/ARCHITECTURE.md` normalization task.
- Issue #5203 remains the separate BuilderOps Model Inquiry capability-resolution repair.

## Relationship To The Shared Epic

The shared epic is a validation hub, never pickup work. It binds this delivery to
`docs/REBUILDABLE_SYSTEM_CONTINUITY/` because rebuildability is the first cross-system invariant
set that must use the routed principle kernel. The two directories keep separate owner boundaries
and child ledgers while sharing one terminal integration proof.

## Source Authority

- `docs/DESIGN_PRINCIPLES.md :: System Design Principles`
- `docs/PROJECT_KERNEL.md :: System Principles (must always hold)`
- `docs/MODULAR_ARCHITECTURE.md`
- `docs/architecture/SBS_OPERATING_MODEL.md :: Change classification checklist`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/testing/invariant-tests.md`
- `docs/audits/REBUILDABILITY_RECOVERY_AUTHORITY_AUDIT_2026-08-31.md`
