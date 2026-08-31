# Shared parent epic — whole-system design routing and rebuildable continuity

State: Filed live shared validation hub #5258 (`agent:blocked`). The hub is never direct pickup work
and claims no shipped capability.

## Context

The accepted rebuildability audit showed that the desired retained-authority posture is coherent,
but the system lacks both a compact cross-system principle-routing mechanism and a complete
total-loss convergence proof. PromotionIntent `prom_20260831201315_5d56e3a3` and acceptance receipt
`receipt_20260831201333_74f589be` authorize conversion into the two linked specifications and a
bounded, serial backlog.

## Scope

Validate delivery of `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/` and
`docs/REBUILDABLE_SYSTEM_CONTINUITY/`: stable principle selection, owned effect boundaries,
retained-authority reconstruction, fenced new-bootstrap recovery, authoritative readback, and one
integrated total-loss proof.

## Source Anchors

- `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md :: Cross-Task Invariants / Partial Failure Safety`
- `docs/audits/REBUILDABILITY_RECOVERY_AUTHORITY_AUDIT_2026-08-31.md :: Minimal testable invariant kernel`

## SBS Impact

- Primary subsystem: CES / Architecture boundary.
- Secondary subsystem(s): HKA, SIP, GOV, PDM, DRI, WSP, OEF, Builder System, Platform/Ops.
- Write class: governance-bearing specification and later authority-bearing/mechanical/derived child work.
- Persistence impact: retained documents and document-backed receipts remain continuity authority;
  operational safety records require explicit owner policy.
- Derived/rebuildable impact: DBs, indexes, embeddings, queues, caches, and projections are rebuilt
  only from declared durable sources and recipes.
- New or changed contract: change-specific principle packets and fenced new-bootstrap recovery.
- Owner-doc impact: promotion only after child and integrated acceptance.
- Transition debt impact: retires ambiguous restore-first and generic-wrapper interpretations.
- Boundary risk: a projection, backup, runtime record, or Builder workflow must never become Product
  meaning or cross-system design authority.

## Constraints

- No implementation is performed from the epic.
- No backup, WAL, restore, generic provider layer, generic port wrapper, daemon, or write-capable
  doctor is implied.
- Existing owner Issues are linked or re-contracted where scope overlaps; do not duplicate #5056,
  #5067, #2143 and its MVR chain, #5162, #4659, #2899, or #3553.
- Delivery remains serial unless independent ready scope and isolated ownership are proven.

## Acceptance Criteria

- [ ] Both capability ledgers are terminal and every delivered child has an exact-merge receipt.
  - Verify: runtime receipt: `builderops.epic-delivery-ledger.v1`
- [ ] The routed principle packet governs the integrated total-loss fixture without becoming a new
  authority source.
  - Verify: `tests/architecture/test_design_principle_routing.py::test_total_loss_change_selects_rebuildability_authority_packet`
- [ ] Product, MVR, and BuilderOps loss paths fence first, rebuild/read back authority, and activate
  only after convergence without replaying or inventing external effects.
  - Verify: `tests/integration/test_rebuildable_system_continuity.py::test_total_loss_converges_from_retained_authority_without_effect_replay`
- [ ] Owner docs promote only evidence-backed current truth and record unresolved operational
  exceptions explicitly.
  - Verify: doc writeback at `docs/REBUILDABLE_SYSTEM_CONTINUITY/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`

## Implementation Tasks

See the ordered ledgers in both capability READMEs. DSP-01 / #5260 is the only initially
pickup-ready child. Later
children are filed after their prerequisite receipt is live; existing overlapping Issues retain
their own lifecycle authority.

## Validation / Acceptance Path

The epic remains `agent:blocked` with `action:wait-dependency` until both child ledgers and the
cross-system proof are terminal. Each child posts an exact-SHA receipt. The last child re-reads live
Issue/PR authority, runs the integration proof, records the owner-doc disposition, and hands the
epic to `verification-and-closure`.

## Out of Scope

- Direct runtime work, host operations, deployment, backup/restore implementation, destructive loss
  testing outside isolated fixtures, or closure of existing independent epics.
