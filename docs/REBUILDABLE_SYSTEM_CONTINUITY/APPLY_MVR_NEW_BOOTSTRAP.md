---
name: Apply MVR New Bootstrap
description: Implement fenced fresh-epoch discovery, readback, convergence, and activation on the existing MVR path.
task_id: RSC-06
github_issue:
source_anchor: "docs/REBUILDABLE_SYSTEM_CONTINUITY/SPECIFY_MVR_NEW_BOOTSTRAP.md :: Acceptance Criteria"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-05, live MVR dependency reconciliation]
depends_on: [SPECIFY_MVR_NEW_BOOTSTRAP.md]
can_parallelize_with: []
---

# Apply MVR New Bootstrap

## Purpose

Make total loss of operational lineage safe on the production MVR control path without widening
MVR activation or restoring unknown state.

## What This Task Does

Implement the accepted state machine through existing instance-state, ownership, lease, and
supervisor owners. A fresh epoch disables effects, performs canonical source/config and host
readback, refuses conflicts/unknowns, writes a convergence receipt, then activates only the
explicitly proven binding set.

## Concretely

Stateful integration tests erase only isolated MVR operational metadata, retain source/config and
simulated host authority, restart twice, and prove stable epoch, no effect before convergence, and
idempotent activation.

## Why This Matters

The safest total-loss behavior is not useful until the real production choke points enforce it
across restart and retry.

## Acceptance Criteria

- [ ] Missing lineage creates one durable fresh epoch, fences every MVR effect path, and remains
  stable across restart/retry.
  - Verify: `tests/instance/test_mvr_fresh_bootstrap.py::test_missing_lineage_creates_restart_stable_fenced_epoch`
- [ ] Authoritative source/config/host readback either converges to an explicit binding set or
  returns typed conflict/unknown without activation.
  - Verify: `tests/instance/test_mvr_fresh_bootstrap.py::test_readback_conflict_or_unknown_cannot_activate`
- [ ] Activation requires the exact convergence receipt and never replays an effect whose prior
  outcome is unknown.
  - Verify: `tests/instance/test_mvr_fresh_bootstrap.py::test_activation_requires_receipt_and_does_not_replay_unknown_effects`

## How To Verify Pre-Merge

- `pytest -q tests/instance/test_mvr_fresh_bootstrap.py`
- Run all MVR/instance-state suites required by the actual diff under the host lease.

## Out Of Scope

- Live host activation, destructive production tests, second-vault activation beyond existing MVR
  authority, or a new supervisor/registry.

## Restart / Durability Posture

Epoch identity, fence state, readback evidence digest, convergence outcome, and activation receipt
are durable. Restart never promotes an incomplete or conflicting epoch.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/REBUILDABLE_SYSTEM_CONTINUITY/SPECIFY_MVR_NEW_BOOTSTRAP.md`

## Related GitHub Issues

File only after live reconciliation with #2143 and its active prerequisite chain.
