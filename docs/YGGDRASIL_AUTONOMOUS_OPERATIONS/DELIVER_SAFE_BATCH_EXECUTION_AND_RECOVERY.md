---
name: Deliver Safe Batch Execution and Recovery
description: Execute bounded homogeneous operation batches with item receipts, truthful partial failure, cancellation, and resume
task_id: AUTOOPS-08
github_issue: 5337
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Batch semantics"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-03, AUTOOPS-04, AUTOOPS-05, AUTOOPS-06, AUTOOPS-07]
depends_on: [CONSOLIDATE_DISCOVERY_AND_READ_OPERATIONS.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md, DELIVER_IDENTITY_PRESERVING_MOVE_AND_RENAME.md, DELIVER_CLASSIFICATION_TAGGING_AND_ORDERING.md, COMPOSE_ARCHIVE_AND_RESTORE_OPERATIONS.md]
can_parallelize_with: []
---

# Deliver Safe Batch Execution and Recovery

## Purpose

Let a bounded delegation act over many artifacts without concealing per-item effects or demanding repeated approval.

## What This Task Does

Implement preview, bounded selection, per-item execution, aggregate progress, cancellation, restart-safe
resume, and recovery for supported operation kinds. Reuse the single-operation kernel for each effect.

## Concretely

```text
batch.preview(kind="artifact.tags.add", selector=..., limit=100) -> immutable candidate digest
batch.execute(preview_id=..., delegation=...) -> completed=73 conflicted=2 refused=1 pending=24
```

## Why This Matters

Batch autonomy is useful only when partial completion is inspectable and replay cannot duplicate effects.

## Acceptance Criteria

- [ ] Preview binds selector, candidate digest, policy ceiling, operation kind, and bounded cardinality.
  Verify: `tests/operations/test_batch_operations.py::test_batch_preview_binds_scope_digest_policy_and_limit`
- [ ] Execution records an item outcome/receipt and a truthful aggregate for mixed success, conflict, and refusal.
  Verify: `tests/operations/test_batch_operations.py::test_batch_execution_preserves_every_item_outcome_and_aggregate_truth`
- [ ] Cancellation, process loss, and resume never duplicate completed effects or skip unresolved items.
  Verify: `tests/operations/test_batch_operations_restart.py::test_batch_cancel_and_restart_resume_are_idempotent`
- [ ] Candidate drift after preview is detected per item and cannot expand delegated scope.
  Verify: `tests/operations/test_batch_operations.py::test_batch_candidate_drift_conflicts_without_scope_expansion`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_batch_operations.py tests/operations/test_batch_operations_restart.py`
- `ruff check app tests`

## Out of Scope

- Distributed transactions, unbounded jobs, cross-vault batches, or automatic rollback of valid committed items.

## Restart / Durability Posture

Preview identity, candidate digest, item states, receipts, cancellation, and recovery cursor are durable.
After restart, the user sees exact completed and unresolved work rather than a reset progress bar.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Related GitHub Issues

Block on AUTOOPS-03 through AUTOOPS-07. TCD hint: `fresh_issue_agent`, helper budget 1, strongest
reliable capability at high reasoning for durable state, concurrency, and partial failure.
