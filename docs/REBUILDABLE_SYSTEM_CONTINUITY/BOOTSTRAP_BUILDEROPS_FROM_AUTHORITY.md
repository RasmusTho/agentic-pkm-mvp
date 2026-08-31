---
name: Bootstrap BuilderOps From Authority
description: Seed a fresh BuilderOps authority epoch, read GitHub truth, reconcile, and enable writers only after convergence.
task_id: RSC-07
github_issue:
source_anchor: "docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md :: rebuildable deployment posture"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-01]
depends_on: [RSC-01]
can_parallelize_with: []
---

# Bootstrap BuilderOps From Authority

## Purpose

Complete the already accepted backup-non-gating BuilderOps posture with an explicit fresh-database
authority bootstrap rather than a restore-assuming recovery record.

## What This Task Does

Seed a fresh authority epoch and reconciliation fence, keep all BuilderOps writers/executors
disabled, read authenticated GitHub Issue/PR/lifecycle truth and configured source/image authority,
record typed unknowns/conflicts, then enable writers only after one receipt-bound convergence.
Historical recovery records remain readable but are not required to invent an LSN or old epoch.

## Concretely

An isolated control-plane test starts from migrations in an empty database, provides authenticated
GitHub fixtures, restarts during readback, and proves deterministic convergence and no dual writer.

## Why This Matters

#5056 establishes rebuildable deployment, but an empty operational database still needs a safe way
to reacquire current external authority without replaying old actions.

## Acceptance Criteria

- [ ] Fresh migrations seed an inactive authority epoch/fence without requiring a restored LSN,
  backup, or fabricated recovery history.
  - Verify: `tests/builderops/test_fresh_authority_bootstrap.py::test_empty_database_seeds_inactive_epoch_without_restore_history`
- [ ] Authenticated GitHub and configured source/image readback converge lifecycle truth or produce
  typed unknown/conflict while writers remain disabled.
  - Verify: `tests/builderops/test_fresh_authority_bootstrap.py::test_authenticated_readback_must_converge_before_writers_enable`
- [ ] Restart/retry is idempotent, no dual writer is admitted, and unknown historical effects are
  reconciled rather than replayed.
  - Verify: `tests/builderops/test_fresh_authority_bootstrap.py::test_restart_is_idempotent_and_unknown_effects_are_not_replayed`

## How To Verify Pre-Merge

- `pytest -q tests/builderops/test_fresh_authority_bootstrap.py`
- Run the BuilderOps migration, authority, and deployment-contract suites selected from the diff.

## Out Of Scope

- Live VM activation, backup/restore implementation, GitHub mutations during readback, or broadening
  #5056's deployment scope.

## Restart / Durability Posture

The fresh epoch, fence, readback cursor/evidence digest, conflicts, and convergence receipt are
durable. Writer enablement is derived only from the matching completed epoch receipt.

## Related Docs

- `docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md`
- `docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md`

## Related GitHub Issues

Coordinate with #5056; do not replace its later live activation acceptance.
