---
name: Execute Topology-Only Prod Cutover
description: Switch a proven known-good runtime onto the new artifact graph without concurrent feature or migration change.
task_id: STARTUP-05
github_issue: 4918
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: [STARTUP-04]
depends_on: [PROVE_PROMOTION_TEST_RECEIPTS.md]
can_parallelize_with: []
---

# Execute Topology-Only Prod Cutover

## Purpose

Move only topology after the same app/schema has already been proven, preserving a fast recovery path.

## What This Task Does

Fences old writers, proves backup and rollback anchor, activates the exact artifact graph, then verifies digest, vault identity, schema, writer guard, gateway, and UI. It rehearses rollback and host/Colima restart before legacy deletion.

## Concretely

The cutover plan names one digest and no migration or feature delta. Any ambiguous vault, absent anchor, cross-channel overlap, or unknown migration state is a hard stop.

## Why This Matters

Topology change must not hide an application or data migration incident.

## Acceptance Criteria

- [ ] Live acceptance receipt proves fence, backup, exact digest, schema, vault identity, writer guard, gateway, UI, rollback rehearsal, and host restart rehearsal. Verify: operator receipt linked from the governing issue.
- [ ] Vault content is never rewound by rollback. Verify: live rollback drill receipt with before/after vault continuity digest.

## How to Verify (Pre-Merge)

Review the bounded operator plan and validate all automation in isolated test fixtures; live execution is separately operator-gated.

## Out of Scope

Feature release, forward-only migration, or legacy removal.

## Related Docs

`docs/deployment/PINNED_IMAGE_CUTOVER/README.md`; `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.

## Related GitHub Issues

Filed ownership: #4918 (P5, operator-gated), under parent validation hub #4913. The existing operator-gated cutover issue was reconciled before filing; this task does not duplicate or silently supersede that capability.
