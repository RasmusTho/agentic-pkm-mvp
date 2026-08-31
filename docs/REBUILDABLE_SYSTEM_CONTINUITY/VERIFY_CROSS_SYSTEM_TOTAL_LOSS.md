---
name: Verify Cross-System Total Loss
description: Prove Product reconstruction plus MVR and BuilderOps fresh-epoch convergence under one exact-head acceptance matrix.
task_id: RSC-08
github_issue:
source_anchor: "docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md :: Capability Acceptance"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-04, RSC-06, RSC-07]
depends_on: [DIAGNOSE_MIRROR_CORRUPTION.md, APPLY_MVR_NEW_BOOTSTRAP.md, BOOTSTRAP_BUILDEROPS_FROM_AUTHORITY.md]
can_parallelize_with: []
---

# Verify Cross-System Total Loss

## Purpose

Demonstrate that the independently owned loss paths compose without hidden authority, premature
readiness, duplicate effects, or conflicting activation claims.

## What This Task Does

Run one isolated acceptance matrix from the retained continuity set and empty/corrupt machine
stores. Product mirrors rebuild from source/recipe tuples. MVR and BuilderOps enter fresh fenced
epochs, read their authoritative sources, converge, and activate only from exact receipts. The test
also exercises interruption, duplicate replay, missing provenance, conflicting readback, and doctor
output.

## Concretely

The production-equivalent test emits a redacted `rebuildable_system_continuity.v1` receipt binding
the selected design packet, exact repository head, retained-source digest, epoch outcomes, and test
matrix results.

## Why This Matters

Green component tests cannot prove that total-loss behavior remains safe when Product, runtime
ownership, and Builder control-plane recovery happen together.

## Acceptance Criteria

- [ ] Product meaning and canonical identities converge from retained authority while all incomplete
  mirrors remain unready.
  - Verify: `tests/integration/test_rebuildable_system_continuity.py::test_product_converges_without_serving_incomplete_mirrors`
- [ ] MVR and BuilderOps activate only from their matching fresh-epoch convergence receipts after
  authoritative readback; conflicts remain fenced.
  - Verify: `tests/integration/test_rebuildable_system_continuity.py::test_operational_epochs_require_matching_readback_receipts`
- [ ] Duplicate/restart paths are idempotent and no unknown durable or external effect is replayed,
  invented, or silently declared complete.
  - Verify: `tests/integration/test_rebuildable_system_continuity.py::test_total_loss_converges_from_retained_authority_without_effect_replay`
- [ ] The redacted terminal receipt binds exact head, design packet, source digest, owner-specific
  epochs, and the complete matrix, then drives the shared epic owner-doc disposition.
  - Verify: runtime receipt: `rebuildable_system_continuity.v1`

## How To Verify Pre-Merge

- `pytest -q tests/integration/test_rebuildable_system_continuity.py`
- Run every child-focused suite on the exact PR head under required host leases.

## Out Of Scope

- Production data deletion, live host rebuild, backup/restore drills, or automatic closure of
  independent MVR/BuilderOps/GAF Issues.

## Restart / Durability Posture

The acceptance fixture kills and restarts each path at declared partial-failure points. Only
owner-specific durable receipts survive as accountability evidence; rebuildable projections are
recreated and never promoted to authority.

## Related Docs

- `docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md`
- `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md`

## Related GitHub Issues

Shared parent epic: #5258.
