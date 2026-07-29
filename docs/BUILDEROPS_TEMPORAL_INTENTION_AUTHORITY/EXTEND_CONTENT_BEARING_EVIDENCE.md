---
name: Extend Temporal-Intention Evidence Beyond The Opaque Record
description: Add only the content or identifier fields explicitly authorized by an accepted privacy and retention decision.
task_id: TIA-03
github_issue: 4378
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D7 — Deferred capabilities require separate gates
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: [TIA-01, TIA-02]
depends_on: [ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md, DECIDE_PRIVACY_RETENTION_AND_ERASURE.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high–xhigh"
capability_rationale: "Any content, identifier, derivative, or key-material expansion is a high-risk data and privacy boundary."
---

# Extend Temporal-Intention Evidence Beyond The Opaque Record

## Purpose

Implement a narrowly authorized content or identity extension only after TIA-02 records an accepted
privacy/retention decision and TIA-01 establishes the canonical opaque transaction path.

## What This Task Does

- Adds only the fields and purposes explicitly authorized by the accepted TIA-02 ADR.
- Extends the PostgreSQL envelope, receipt, outbox, observability, backup, and projection contracts
  consistently.
- Adds fail-closed validation, retention classification, and access controls required by the
  accepted decision.

## Concretely

The task contract must be reconciled to the accepted TIA-02 decision before pickup. If the decision
does not authorize a bounded content or identity extension, this Issue is superseded or closed
without implementation.

## Why This Matters

Content and linkable identity cannot be smuggled into the opaque core through a “small” schema
extension; every durability surface must share one explicit policy.

## Acceptance Criteria

- [ ] The Issue body is reconciled to an accepted TIA-02 ADR and names the exact authorized fields,
  purposes, retention classes, access controls, and prohibited fields before `agent:ready`.
  - Verify: `runtime receipt: temporal_intention_tia03_contract_reconciliation.v1`
- [ ] Every authorized field has one explicit mapping across authoritative record, receipt, outbox,
  log/metric policy, backup treatment, and projection, with unknown fields rejected.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_content_policy.py::test_authorized_fields_map_across_every_durable_surface`
- [ ] Content or identity outside the accepted policy fails before commit and leaves no receipt,
  outbox intent, log value, metric label, or projection residue.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_content_policy.py::test_unauthorized_content_fails_without_residue`
- [ ] Equal replay and conflicting reuse preserve TIA-01 atomicity and cannot change authorized
  content under an existing idempotency identity.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_content_policy.py::test_content_extension_preserves_idempotent_conflict_semantics`

## How to Verify (Pre-Merge)

- Run the named privacy-policy, transaction, replay, receipt, and outbox tests.
- Run the TIA-01 regression suite.
- Run the data/privacy review-before-CI convergence gate.

## Out of Scope

- Any field not explicitly authorized by the accepted TIA-02 decision.
- Collectors, cross-host topology, migration, UI, retention execution, or physical erasure.
- Replacing the opaque identity or transaction kernel.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/DECIDE_PRIVACY_RETENTION_AND_ERASURE.md`

## Related GitHub Issues

- Live task: [#4378](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4378).
