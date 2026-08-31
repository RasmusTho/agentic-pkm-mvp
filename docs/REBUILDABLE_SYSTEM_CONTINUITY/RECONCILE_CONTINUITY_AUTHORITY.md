---
name: Reconcile Continuity Authority
description: Align owner documents with retained authority, rebuildable mirrors, and fenced new-bootstrap recovery.
task_id: RSC-01
github_issue:
source_anchor: "docs/audits/REBUILDABILITY_RECOVERY_AUTHORITY_AUDIT_2026-08-31.md :: 3. Anchored findings"
parent_capability: Rebuildable System Continuity
prerequisites: [DSP-01]
depends_on: [../WHOLE_SYSTEM_DESIGN_PRINCIPLES/ESTABLISH_PRINCIPLE_KERNEL.md]
can_parallelize_with: []
---

# Reconcile Continuity Authority

## Purpose

Resolve the audit's documentation conflicts before runtime work so each later slice has one
authority, rebuildability, and failure posture.

## What This Task Does

Amend existing owner docs to state that retained human artifacts, companions, and document-backed
receipts are continuity authority; machine mirrors are rebuildable; missing operational lineage
starts a fenced new bootstrap. Clarify diagnostic JSONL/dump retention and mark historical
restore-first material as superseded where current owner decisions already do so.

## Concretely

Documentation guards assert consistent classification across semantic authority, operations,
dependencies, deployment, BuilderOps, and GAF/HKA recovery references.

## Why This Matters

Runtime code cannot safely choose rebuild, retain, restore, or refuse while owner documents imply
different sources of truth.

## Acceptance Criteria

- [ ] Owner docs use one continuity classification and explicitly distinguish semantic authority,
  rebuildable mirrors, retained evidence, and operational safety state.
  - Verify: `tests/architecture/test_rebuildability_authority_docs.py::test_owner_docs_share_one_continuity_classification`
- [ ] Diagnostic JSONL/dumps and optional backups are evidence/ergonomics only and never worker
  queue, readiness, semantic authority, or mandatory restore proof.
  - Verify: `tests/architecture/test_rebuildability_authority_docs.py::test_diagnostic_retention_is_not_recovery_authority`
- [ ] Historical HKA/BuilderOps restore-first proposals are pointed to as superseded or blocked and
  are not promoted into current capability claims.
  - Verify: `tests/architecture/test_rebuildability_authority_docs.py::test_historical_recovery_material_cannot_claim_active_capability`

## How To Verify Pre-Merge

- `pytest -q tests/architecture/test_rebuildability_authority_docs.py`
- `git diff --check`

## Out Of Scope

- Runtime reconstruction, backup/WAL implementation, deleting historical evidence, or closing
  #5067/#5056/#2143.

## Related Docs

- `docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`
- `docs/OPERATIONS.md`
- `docs/DEPENDENCIES.md`

## Related GitHub Issues

Depends on DSP-01. Existing #5056 and #5067 retain their distinct live state.
