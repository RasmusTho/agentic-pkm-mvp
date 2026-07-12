---
name: Repair Derived State Deterministically
description: Rebuild or suppress DRI after correction, revocation and identity merge.
task_id: GKES-07
source_anchor: docs/boundaries/DRI.md :: Policy obligations
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-02, GKES-04]
depends_on: [MAKE_HEIMDAL_INTAKE_DURABLE.md, CONSOLIDATE_SEMANTIC_IDENTITY_AUTHORITY.md]
can_parallelize_with: [RECONCILE_TERMINAL_AUTHORITY_OUTCOMES]
---

# Repair Derived State Deterministically

## Purpose

Keep DRI rebuildable and non-authoritative when sources are corrected, revoked or merged.

## What This Task Does

Implement durable-source-driven invalidation, suppression and rebuild/resume semantics. The same source history must produce equivalent derived state regardless of batch boundaries or restart.

## Concretely

Build domain repair rules on current checkpoint/replay mechanisms. Preserve source metadata and never treat DRI as the only holder of identity, evidence or authority.

## Why This Matters

Repair before source and identity stability would cement wrong derivations and create expensive manual cleanup.

## Acceptance Criteria

- [ ] A correction, revocation or identity merge suppresses/rebuilds affected derived state through the production path. Verify: `tests/indexer/test_derived_state_repair.py::test_correction_revocation_and_merge_repair_derived_state`.
- [ ] Equivalent source history yields equivalent state across batch sizes and restart/resume. Verify: `tests/indexer/test_derived_state_repair.py::test_derived_rebuild_is_deterministic_across_batches_and_restart`.
- [ ] Full rebuild matches incremental repair and source metadata remains intact. Verify: `tests/indexer/test_derived_state_repair.py::test_full_rebuild_matches_incremental_repair_with_provenance`.

## How to Verify (Pre-Merge)

- `pytest -q tests/indexer/test_derived_state_repair.py tests/indexer/test_identity_provenance.py`
- `ruff check app tests`

## Out of Scope

Provider selection, graph database adoption, or generic replication/convergence.

## Related Docs

- `docs/boundaries/DRI.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md`

## Related GitHub Issues

Blocked by GKES-02 and GKES-04; final child and parent-closure handoff.
