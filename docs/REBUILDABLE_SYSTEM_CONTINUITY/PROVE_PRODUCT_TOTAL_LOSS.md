---
name: Prove Product Total Loss
description: Establish a fail-closed Product store/readiness kernel that reconstructs only from retained source fixtures.
task_id: RSC-02
github_issue: 5282
source_anchor: "docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md :: Rebuild semantics"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-01]
depends_on: [RECONCILE_CONTINUITY_AUTHORITY.md]
can_parallelize_with: []
---

# Prove Product Total Loss

## Purpose

Turn the declared mirror posture into an executable Product loss/refusal invariant before widening
rebuild coverage.

## What This Task Does

Add isolated retained-source fixtures and production readiness checks for an empty or corrupt
Product database. Rebuild/use binds source identity, source generation/content identity, and
recipe version; `/readyz` stays blocked until reconstruction and integrity verification complete,
while the source-backed recovery write path remains available to perform that rebuild.

## Concretely

The focused integration test captures a canonical pre-loss semantic baseline, deletes only the
isolated machine store, rebuilds from retained source fixtures, and compares meaning-bearing
identities while asserting readiness was false throughout the incomplete interval.

## Why This Matters

A `rebuild_source` declaration is not proof that an empty database cannot be mistaken for valid
empty knowledge.

## Acceptance Criteria

- [ ] Empty and corrupt Product stores refuse readiness/use until source-bound reconstruction and
  integrity verification complete.
  - Verify: `tests/integration/test_product_total_loss.py::test_empty_or_corrupt_store_is_unready_until_verified_rebuild`
- [ ] Rebuilt canonical identities and meaning-bearing fields match the retained-source baseline;
  machine-only ordering or cache bytes are not treated as meaning.
  - Verify: `tests/integration/test_product_total_loss.py::test_retained_sources_reproduce_canonical_meaning_after_total_loss`
- [ ] Missing or mismatched source/generation/recipe provenance yields typed refusal and no silent
  stale or memory fallback.
  - Verify: `tests/integration/test_product_total_loss.py::test_missing_replay_tuple_refuses_without_fallback`

## How To Verify Pre-Merge

- `pytest -q tests/integration/test_product_total_loss.py`
- Run required migration/store tests selected from the actual diff.

## Out Of Scope

- Production destructive tests, queue/relation convergence, MVR, BuilderOps, or backup/restore.

## Related Docs

- `docs/DB_SCHEMA.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`

## Related GitHub Issues

Issue #2899 remains the independent Runtime Correctness Kernel audit.
