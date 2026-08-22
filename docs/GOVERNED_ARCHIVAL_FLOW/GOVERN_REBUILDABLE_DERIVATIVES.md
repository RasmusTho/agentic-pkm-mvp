---
name: Govern Rebuildable Derivatives
description: Classify and diagnose caches, embeddings, indexes, OCR, thumbnails, and other derivatives without promoting them to source authority
task_id: GAF-06
github_issue: 5068
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Artifact-Class Posture"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-01]
depends_on: [DEFINE_ARCHIVAL_CONTRACT.md]
can_parallelize_with: [Adapt Retained Source Artifacts, Adapt Human Artifact Recovery]
---

# Govern Rebuildable Derivatives

## Purpose

Make the archival flow explicitly refuse rebuildable artifacts as source authority while providing
a read-only doctor that proves whether safe discard and rebuild remain possible.

## What This Task Does

- Add derivative disposition values and a read-only DRI-facing classifier under `app.archival/`.
- Require a resolvable authoritative source identity, source generation, and rebuild recipe/version
  before classifying a derivative as safely rebuildable or discardable.
- Diagnose missing source, stale lineage, missing recipe, and accidental source-authority claims as
  typed findings without changing artifacts or owner state.
- Route an explicitly non-rebuildable derivative to HKA or retained-source admission before it can
  enter archival flow; reclassification is an owner action, not a doctor side effect.
- Cover embeddings, indexes, OCR, thumbnails, and cache examples without implementing their rebuild
  engines.

## Concretely

```bash
pytest -q tests/archival/test_derived_disposition.py
```

The suite evaluates descriptors against fake owner-native source and recipe lookups. It records no
archive representation, receipt, deletion, or reclassification while diagnosing.

## Why This Matters

Archiving every durable-looking file multiplies cost and can make a stale derivative appear more
authoritative than its source. A loud classifier preserves recovery confidence without duplicating
meaning.

## Acceptance Criteria

- [ ] A derivative with a resolvable authoritative source and rebuild recipe remains non-authority
      and cannot be admitted as the sole archived source of meaning.
      Verify: `tests/archival/test_derived_disposition.py::test_rebuildable_derivative_is_not_archive_authority`
- [ ] Missing source identity, source generation, or rebuild recipe/version yields a typed loud
      finding rather than a safe-discard or archived classification.
      Verify: `tests/archival/test_derived_disposition.py::test_missing_source_or_rebuild_recipe_is_loud`
- [ ] Explicitly non-rebuildable material must be reclassified through an HKA or retained-source
      owner adapter before archival admission.
      Verify: `tests/archival/test_derived_disposition.py::test_explicit_nonrebuildable_reclassification_routes_to_owner_adapter`
- [ ] Doctor execution is read-only and cannot write receipts, mutate owner state, delete bytes, or
      change a classification.
      Verify: `tests/archival/test_derived_disposition.py::test_derivative_doctor_is_read_only`
- [ ] The common contract documents DRI ownership and the refusal to use derivatives as last-copy
      source authority.
      Verify: doc writeback at `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md :: Rebuildable derivative disposition`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_derived_disposition.py`
2. `pytest -q tests/architecture/test_governed_archival_contract.py`
3. `ruff check app/archival tests/archival`

## Out of Scope

- Rebuilding embeddings, indexes, OCR, thumbnails, or caches; selecting vector/index technology;
  retention decisions for a newly reclassified source; or mutation by the doctor.
- Scanning arbitrary directories to infer artifacts or sources.

## Restart / Durability Posture

The classifier and doctor keep no authority or progress state. They re-read owner-native source and
recipe evidence on every run. A process interruption yields no transition or terminal claim; a later
run may produce a different finding only when the underlying authoritative evidence changed.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/testing/invariant-tests.md`

## Related GitHub Issues

One bounded classification/doctor Issue. Execution context: `fresh_issue_agent`; helper budget `0`.
TCD hint: Terra / medium because behavior is read-only, locally testable, and follows the GAF-01
contract; escalate only if live DRI ownership or persistence coupling is discovered.
