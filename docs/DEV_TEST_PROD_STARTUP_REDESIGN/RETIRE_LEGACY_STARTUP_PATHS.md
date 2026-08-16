---
name: Retire Legacy Startup Paths
description: Remove only unsupported legacy startup paths after soak and recovery evidence.
task_id: STARTUP-06
github_issue: 4919
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: [STARTUP-05]
depends_on: [EXECUTE_TOPOLOGY_ONLY_PROD_CUTOVER.md]
can_parallelize_with: []
---

# Retire Legacy Startup Paths

## Purpose

Remove the old bootstrap and bind-mount routes only after evidence says they are no longer recovery dependencies.

## What This Task Does

Inventories callers, preserves authority data and rollback floors, and removes paths only after soak, recovery/rollback drills, and one subsequent digest promotion.

## Concretely

`legacy-startup inventory` produces supported-caller evidence before any deletion proposal.

## Why This Matters

Deleting an undocumented fallback before a successful recovery drill converts technical debt into an outage.

## Acceptance Criteria

- [ ] Every retired path has a no-supported-caller receipt and preserved rollback-floor evidence. Verify: governing issue receipt.
- [ ] A subsequent digest promotion and recovery/rollback drill succeeded before removal. Verify: linked promotion and drill receipts.

## How to Verify (Pre-Merge)

Run caller-inventory tests and review the removal list against live receipts.

## Out of Scope

Deleting vaults, volumes, backups, or authority data.

## Related Docs

`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`.

## Related GitHub Issues

Filed ownership: #4919 (P6, dependency-blocked/post-soak), under parent validation hub #4913. The parent/child overlap was reconciled before filing; retain the post-soak readiness constraint and do not mark this task ready from a docs-only claim.
