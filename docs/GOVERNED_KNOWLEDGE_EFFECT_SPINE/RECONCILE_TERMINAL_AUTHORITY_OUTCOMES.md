---
name: Reconcile Terminal Authority Outcomes
description: Give each authorized effect one durable terminal receipt or recovery state.
task_id: GKES-06
source_anchor: docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Outputs
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-01, GKES-05]
depends_on: [DEFINE_EFFECT_SPINE_CONTRACTS.md, ENFORCE_GOVERNED_EFFECT_TOKENS.md]
can_parallelize_with: [CONSOLIDATE_SEMANTIC_IDENTITY_AUTHORITY]
---

# Reconcile Terminal Authority Outcomes

## Purpose

Make the state after an effect crash inspectable and safely recoverable.

## What This Task Does

Add a durable operation lifecycle: started, recoverable, terminal success, terminal failure/quarantine. Reconcile mutation-after-before-receipt failures into exactly one logical terminal outcome and AuthorityReceipt.

## Concretely

Prefer an idempotent journal/outbox plus reconciliation over a distributed transaction unless the verified runtime needs stronger guarantees.

## Why This Matters

Without terminal continuity, operators cannot distinguish completed mutation from failed mutation and risk duplicate effects.

## Acceptance Criteria

- [ ] A crash after mutation and before receipt leaves an explicit recoverable state. Verify: `tests/api/test_capture_authority_receipts.py::test_capture_crash_after_mutation_records_recovery_state`.
- [ ] Reconciliation yields exactly one terminal logical outcome and receipt for a retried operation identity. Verify: `tests/api/test_capture_authority_receipts.py::test_capture_reconciliation_emits_single_terminal_authority_receipt`.
- [ ] Terminal outcome and receipt survive restart and permanent failure remains inspectable. Verify: `tests/api/test_capture_authority_receipts.py::test_capture_terminal_outcome_survives_restart_and_records_permanent_failure`.

## How to Verify (Pre-Merge)

- `pytest -q tests/api/test_capture_authority_receipts.py tests/runtime/test_receipt_event_boundary.py`
- `ruff check app tests`

## Out of Scope

Distributed transactions or rewriting historical receipts.

## Related Docs

- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`

## Related GitHub Issues

Blocked by GKES-05.
