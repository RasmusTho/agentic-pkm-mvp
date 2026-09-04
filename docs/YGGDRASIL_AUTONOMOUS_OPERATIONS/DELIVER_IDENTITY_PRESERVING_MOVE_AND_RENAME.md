---
name: Deliver Identity-Preserving Move and Rename
description: Add governed placement changes that preserve artifact identity and refuse collisions or stale generations
task_id: AUTOOPS-05
github_issue: 5334
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Identity, path, and placement"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02, AUTOOPS-04]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md]
can_parallelize_with: []
---

# Deliver Identity-Preserving Move and Rename

## Purpose

Let humans and agents change artifact placement or display name without changing identity or clobbering data.

## What This Task Does

Implement owner-native move and rename handlers with destination reservation, expected generation,
collision refusal, stable ID preservation, projection convergence, and compensating recovery.

## Concretely

```text
artifact.move(id="a-17", destination="projects/x", expected_version=8)
  -> reserve -> owner move -> verify identity -> converge projections -> receipt
```

## Why This Matters

Path-based mutation makes references brittle and can turn a harmless rename into data loss.

## Acceptance Criteria

- [ ] Move and rename preserve stable artifact identity and update locator projections atomically or recoverably.
  Verify: `tests/operations/test_placement_operations.py::test_move_and_rename_preserve_identity_and_converge_locators`
- [ ] Destination collision, stale generation, and cross-vault scope mismatch fail before clobbering.
  Verify: `tests/operations/test_placement_operations.py::test_placement_refuses_collision_stale_generation_and_scope_mismatch`
- [ ] Failure after reservation leaves the original authoritative and supports idempotent recovery.
  Verify: `tests/operations/test_placement_operations.py::test_partial_move_preserves_original_and_recovers_idempotently`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_placement_operations.py`
- `ruff check app tests`

## Out of Scope

- Cross-vault copy semantics, archive transitions, user-interface controls, or arbitrary filesystem moves.

## Restart / Durability Posture

Reservation, generation, terminal receipt, and recovery state survive restart. The source remains
authoritative until destination activation is verified.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Related GitHub Issues

Block on AUTOOPS-02/04. TCD hint: `fresh_issue_agent`, helper budget 1, strongest reliable capability
at high reasoning due to data integrity and concurrency.
