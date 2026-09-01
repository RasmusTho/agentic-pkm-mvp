---
name: Diagnose Mirror Corruption
description: Report typed inventory, provenance, consistency, and hidden-authority failures without mutating owner state.
task_id: RSC-04
github_issue: 5292
source_anchor: "docs/audits/REBUILDABILITY_RECOVERY_AUTHORITY_AUDIT_2026-08-31.md :: DOCTOR"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-02, RSC-03]
depends_on: [PROVE_PRODUCT_TOTAL_LOSS.md, REBUILD_PRODUCT_PROJECTIONS.md]
can_parallelize_with: []
---

# Diagnose Mirror Corruption

## Purpose

Make incomplete rebuildability and hidden authority visible before readiness without granting a
diagnostic path repair or activation rights.

## What This Task Does

Add one typed, read-only Product doctor for durable-path classification, source/recipe provenance,
orphaned/stale projections, DB/source mismatch, and records used as sole meaning or action authority.
Output is redacted or digest-only where content is sensitive.

## Concretely

Production-command tests inspect healthy, stale, corrupt, orphaned, and unclassified isolated
fixtures and compare canonical typed results while asserting no filesystem/database mutation.

## Why This Matters

Rebuild refusal without actionable, bounded evidence would convert safe failure into opaque
operations work.

## Acceptance Criteria

- [ ] Every durable non-document path is classified with owner and rebuild/retention source, or the
  doctor emits a typed unclassified failure.
  - Verify: `tests/ops/test_rebuildability_doctor.py::test_inventory_requires_owner_and_rebuild_or_retention_source`
- [ ] Missing provenance, stale generation, orphaned projection, index drift, and DB/source mismatch
  produce stable typed findings and no false healthy result.
  - Verify: `tests/ops/test_rebuildability_doctor.py::test_doctor_detects_projection_corruption_and_drift`
- [ ] The doctor is read-only, redacts sensitive content, and never repairs, activates, restores, or
  creates authority.
  - Verify: `tests/ops/test_rebuildability_doctor.py::test_doctor_is_redacted_and_non_mutating`

## How To Verify Pre-Merge

- `pytest -q tests/ops/test_rebuildability_doctor.py`
- `git diff --exit-code` after a clean-fixture doctor run.

## Out Of Scope

- Auto-repair, daemonization, host scanning, or destructive production probes.

## Related Docs

- `docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md`
- `docs/OPERATIONS.md`

## Related GitHub Issues

Issue #2899 retains its independent audit ledger.
