---
name: Implement Verified Archival Transition Kernel
description: Implement a storage-neutral transition state machine that verifies destination durability before source retirement and preserves typed retryable liveness
task_id: GAF-02
github_issue: 5064
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-01]
depends_on: [DEFINE_ARCHIVAL_CONTRACT.md]
can_parallelize_with: []
---

# Implement Verified Archival Transition Kernel

## Purpose

Provide the shared mechanism that orders reserve, copy/export, verify, receipt, activate, retire,
restore, cleanup, and liveness without owning artifact meaning or storage state.

## What This Task Does

- Implement the provider-free transition service under `app/archival/` against GAF-01 adapter
  protocols.
- Require destination reservation before bytes, owner-native durable receipt before activation,
  activation before source retirement, and a loud retryable state on every partial failure.
- Bind every operation to artifact identity, owner-native generation, representation ID, policy
  profile, and idempotency key.
- Model `active`, `transition_pending`, `restore_pending`, `erasure_pending`, `restored`, `erased`,
  `unavailable`, and `conflict` without projecting a pending state as terminal success.
- Implement a fake durable adapter and fault-injection harness that proves crash/retry ordering. No
  production adapter is wired in this task.

## Concretely

```bash
pytest -q tests/archival/test_transition_kernel.py
```

The test suite injects failure after reservation, byte persistence, verification, receipt, activation,
retirement, and cleanup. Retrying the same operation converges or refuses stale authority; it never
duplicates a terminal receipt or loses the only readable representation.

## Why This Matters

The shared value is the transition ordering and liveness honesty. A protocol without executable
ordering would let each adapter recreate the same crash windows that HAR-04/HAR-05 had to close.

## Acceptance Criteria

- [ ] A destination becomes active only after its bytes/portable representation, identity proof,
      and owner-native durable receipt exist; the source retires only afterward.
      Verify: `tests/archival/test_transition_kernel.py::test_verified_transition_is_durable_before_source_retirement`
- [ ] Fault injection at every stage preserves a readable source or a typed retryable pending state,
      and idempotent retry converges without duplicate terminal receipts.
      Verify: `tests/archival/test_transition_kernel.py::test_crash_matrix_preserves_source_and_retry_authority`
- [ ] A stale generation, changed policy decision, or changed destination binding is refused before
      effect and cannot retire or erase the current generation.
      Verify: `tests/archival/test_transition_kernel.py::test_stale_generation_and_binding_fail_closed_before_effect`
- [ ] Restore invokes the adapter's production access/governed-write seam and receipts the exact
      verified representation; backend availability alone cannot authorize it.
      Verify: `tests/archival/test_transition_kernel.py::test_restore_requires_owner_access_gate_and_exact_representation`
- [ ] Cleanup failure remains `erasure_pending` and blocks terminal erasure until the adapter proves
      all policy-required representations handled.
      Verify: `tests/archival/test_transition_kernel.py::test_cleanup_failure_cannot_project_terminal_erasure`
- [ ] The kernel stores no global artifact registry or content bytes and can reconstruct operation
      state only through owner-native adapter queries and receipts.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_transition_kernel_has_no_private_persistence_or_content_store`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_transition_kernel.py`
2. `pytest -q tests/architecture/test_governed_archival_contract.py`
3. `ruff check app/archival tests/archival`
4. `mypy app/archival`

## Out of Scope

- Production adapter wiring, database migration, backend provisioning, owner policy changes, or
  user-facing archive browsing.
- Replacing Heimdal's delivered state machine before its adapter task is ready.

## Restart / Durability Posture

The kernel keeps no authoritative in-memory progress. After restart it re-reads owner-native
representations, receipts, generations, and pending cleanup state through the adapter. If durable
state is incomplete or contradictory, the operation is `unavailable`/pending and fails closed; it
never infers completion from a missing process-local value.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md` (created by GAF-01)
- `docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Cross-task invariants`
- `docs/EVENTS.md :: Heimdal local archive restore + all-copy expiry`

## Related GitHub Issues

One bounded implementation Issue. Execution context: `fresh_issue_agent`; helper budget `1` only for
an independent fault-matrix review. TCD hint: Sol / high because this is a stateful data-loss,
concurrency, and erasure mechanism; lowering capability would raise rework and defect cost.
