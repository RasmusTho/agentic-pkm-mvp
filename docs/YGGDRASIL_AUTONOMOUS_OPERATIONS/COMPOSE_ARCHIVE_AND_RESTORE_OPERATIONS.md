---
name: Compose Archive and Restore Operations
description: Expose type-aware archive and restore through the existing governed archival lifecycle
task_id: AUTOOPS-07
github_issue: 5336
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Adapter rules"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md]
can_parallelize_with: []
---

# Compose Archive and Restore Operations

## Purpose

Add archive and restore to shared operations without creating a second lifecycle or retention authority.

## What This Task Does

Adapt the Governed Archival Flow's type-specific providers to operation requests and outcomes,
preserving liveness, generation, policy profile, receipts, and recovery semantics.

## Concretely

```text
artifact.archive(id="a-17", expected_generation=5)
  -> governed archival provider -> archived liveness + authority receipt
artifact.restore(id="a-17", expected_generation=6) -> restored locator or typed conflict
```

## Why This Matters

A generic archive flag would erase type-specific retention, deletion, and recovery guarantees.

## Acceptance Criteria

- [ ] Archive/restore dispatches by artifact class to the existing governed archival production call site.
  Verify: `tests/operations/test_archival_operations.py::test_operations_dispatch_to_governed_archival_providers`
- [ ] Liveness, generation, retention/refusal, and receipt fields survive adapter mapping losslessly.
  Verify: `tests/operations/test_archival_operations.py::test_archival_outcomes_preserve_liveness_generation_policy_and_receipts`
- [ ] Unsupported classes, partial transitions, and stale restore requests fail closed with recovery guidance.
  Verify: `tests/operations/test_archival_operations.py::test_archival_failures_are_typed_and_recoverable`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_archival_operations.py tests/archival`
- `ruff check app tests`

## Out of Scope

- Implementing the archival kernel/providers, changing retention policy, or treating archive as delete.

## Restart / Durability Posture

The archival owner remains durable authority. The operation adapter persists only its operation
join and never reconstructs lifecycle truth from process memory.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-02 and the relevant open Governed Archival Flow owner tasks under parent #5062.
TCD hint: `fresh_issue_agent`, helper budget 1, strongest reliable capability at high reasoning for lifecycle/data safety.
