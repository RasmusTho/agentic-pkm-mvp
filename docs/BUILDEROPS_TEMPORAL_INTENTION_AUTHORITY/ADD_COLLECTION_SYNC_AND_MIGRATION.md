---
name: Add Governed Collection Cross-Host Behavior And Migration
description: Add one separately approved source-admission, topology, and historical-migration path without creating another authority.
task_id: TIA-04
github_issue: 4379
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D7 — Deferred capabilities require separate gates
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: [TIA-01, TIA-02, SOURCE_TOPOLOGY_MIGRATION_DECISION]
depends_on: [ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md, DECIDE_PRIVACY_RETENTION_AND_ERASURE.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high–xhigh"
capability_rationale: "External sources, cross-host delivery, migration, and exactly-once authority reconciliation are high-risk integration and data work."
---

# Add Governed Collection, Cross-Host Behavior, And Migration

## Purpose

Introduce a bounded source and historical-data path only after a separate owner decision selects
the allowed sources, authenticated topology, privacy constraints, reconciliation rules, and
migration authority.

## What This Task Does

- Produces or cites an accepted source/topology/migration decision before implementation.
- Admits data only through the canonical authenticated BuilderOps API and TIA-01 transaction.
- Defines source correlation, retry, conflict, backfill, audit, and cutover semantics without a
  compatibility writer.
- Proves that no collector, host cache, import file, or migration checkpoint becomes canonical
  lifecycle state.

## Concretely

This Issue stays blocked until its broad placeholder is narrowed to one approved source and one
bounded migration or cross-host behavior. If several independent sources are approved, split them
into separate implementation Issues rather than building a generic collector framework.

## Why This Matters

Collectors and migrations are the most likely path for raw identifiers, hidden content, duplicate
admission, and split-brain authority to re-enter after the opaque core is safe.

## Acceptance Criteria

- [ ] An accepted owner decision names the one source, authenticated topology, permitted payload,
  privacy policy, historical scope, conflict authority, and rollback/cutover behavior before the
  Issue becomes ready.
  - Verify: `runtime receipt: temporal_intention_tia04_contract_reconciliation.v1`
- [ ] Every accepted source event reaches the existing authenticated API and canonical transaction;
  no host cache, queue, import artifact, or checkpoint can mutate lifecycle authority directly.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_source_boundary.py::test_source_path_has_one_authenticated_canonical_writer`
- [ ] Retry, cross-host duplication, response loss, and restart converge to one logical identity
  and receipt lineage through TIA-01 replay semantics.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_source_boundary.py::test_cross_host_retry_converges_without_duplicate_authority`
- [ ] Historical import is bounded, auditable, restartable, and rejects ambiguous or conflicting
  source mappings without a compatibility writer.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_migration.py::test_bounded_import_restarts_and_conflicts_fail_closed`

## How to Verify (Pre-Merge)

- Reconcile this task spec and live Issue to the accepted decision before pickup.
- Run the named external-boundary, concurrency, replay, migration, and fault-injection tests.
- Run the external-API/data/migration review-before-CI convergence gate.

## Out of Scope

- A generic collector platform or unapproved additional source.
- Peer-to-peer or file-based authority synchronization.
- Content, identifiers, or derivatives not authorized by TIA-02.
- Product runtime mutation or UI projection.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/DECIDE_PRIVACY_RETENTION_AND_ERASURE.md`

## Related GitHub Issues

- Live task: [#4379](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4379).
