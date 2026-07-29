---
name: Enforce Temporal-Intention Retention And Physical Erasure
description: Implement only the retention and erasure behavior explicitly authorized by the accepted privacy decision.
task_id: TIA-06
github_issue: 4381
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D7 — Deferred capabilities require separate gates
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: [TIA-01, TIA-02]
depends_on: [ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md, DECIDE_PRIVACY_RETENTION_AND_ERASURE.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / xhigh"
capability_rationale: "Physical erasure, backups, immutable receipts, and recovery semantics are irreversible high-risk data work."
---

# Enforce Temporal-Intention Retention And Physical Erasure

## Purpose

Implement retention expiry or physical-erasure behavior only after TIA-02 accepts exact semantics
for canonical records, append-only receipts, outbox rows, projections, logs, metrics, backups, and
recovery copies.

## What This Task Does

- Reconciles this contract to the accepted retention/erasure decision before implementation.
- Implements the narrow retention schedule and erasure mechanism the decision authorizes.
- Preserves or supersedes receipt lineage exactly as the decision requires.
- Emits durable proof of requested, attempted, completed, failed, and reconciled erasure outcomes.

## Concretely

`never_show_again` remains a scope-bound suppression and is never treated as physical deletion.
Physical erasure occurs only through the accepted retention authority and cannot be inferred from a
disposition.

## Why This Matters

Deletion claims are unsafe unless every copy class and recovery path is named and the system can
prove what was removed, what was retained, and why.

## Acceptance Criteria

- [ ] The live Issue and task spec are reconciled to an accepted TIA-02 decision naming retention
  clocks, legal/policy holds, receipt treatment, outbox and projection cleanup, logs/metrics,
  backup/recovery copies, failure reconciliation, and operator evidence before `agent:ready`.
  - Verify: `runtime receipt: temporal_intention_tia06_contract_reconciliation.v1`
- [ ] `never_show_again` never triggers physical deletion and no other disposition is implicitly
  reinterpreted as a retention or erasure command.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_erasure.py::test_dispositions_never_imply_physical_erasure`
- [ ] The authorized erasure workflow is idempotent, fenced, crash-recoverable, and records
  append-only outcome evidence without falsely claiming completion.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_erasure.py::test_erasure_is_fenced_recoverable_and_truthful`
- [ ] Every copy class named by the accepted decision has a passing retained-or-erased assertion,
  including canonical rows, receipts, outbox/dead letters, projections, logs/metrics, and
  backup/recovery copies.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_erasure.py::test_erasure_policy_covers_every_declared_copy_class`
- [ ] Restore or rebuild cannot resurrect erased authority or silently discard retained receipt
  evidence.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_erasure.py::test_restore_and_rebuild_preserve_erasure_decision`

## How to Verify (Pre-Merge)

- Reconcile the contract to the accepted decision.
- Run the named retention, erasure, restore, backup, receipt, outbox, and projection tests.
- Run the data/migration/state-machine review-before-CI convergence gate.
- Produce the operator-visible erasure verification receipt required by the accepted decision.

## Out of Scope

- Treating a disposition as a deletion request.
- Inventing a retention schedule or erasure meaning not accepted by TIA-02.
- Content collection, migration, cross-host topology, or UI.
- Weakening append-only receipt semantics without an explicit superseding owner decision.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/DECIDE_PRIVACY_RETENTION_AND_ERASURE.md`

## Related GitHub Issues

- Live task: [#4381](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4381).
