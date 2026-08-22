---
name: Verify Cross-Class Archival Lifecycle
description: Prove the delivered adapters preserve owner authority and lifecycle truth across representative artifact classes, then emit the parent validation receipt
task_id: GAF-07
github_issue: 5069
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Capability Acceptance Criteria"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-03, GAF-04, GAF-05, GAF-06]
depends_on: [ADAPT_HEIMDAL_RAW_MEDIA.md, ADAPT_RETAINED_SOURCE_ARTIFACTS.md, ADAPT_HUMAN_ARTIFACT_RECOVERY.md, GOVERN_REBUILDABLE_DERIVATIVES.md]
can_parallelize_with: []
---

# Verify Cross-Class Archival Lifecycle

## Purpose

Validate the complete capability through production adapter paths and produce the durable evidence
required for parent acceptance and owner-doc promotion.

## What This Task Does

- Add a cross-class conformance harness for raw audio, image, video, and document captures; one
  retained binary media source; one retained document; one HKA artifact; and representative
  derivative/cache descriptors.
- Exercise identity and provenance continuity, verified activation, gated access, restore, stale
  generation/conflict refusal, class-specific retention/revocation/deletion, partial failures, and
  typed liveness through the production adapter seams.
- Run the read-only doctor across orphan, missing-source, stale-generation, pending-cleanup, and
  healthy cases and assert that it performs no mutation.
- Emit a redacted durable `governed-archival-validation.v1` receipt binding exact commit, adapter
  versions, test matrix, owner-policy versions, outcomes, and unresolved findings.
- Post the exact-SHA receipt to the parent validation hub and hand off parent closure plus one
  owner-doc promotion pass; do not close the parent from this child before readback.

## Concretely

```bash
pytest -q tests/archival/test_cross_class_conformance.py
python3 scripts/verify_governed_archival_flow.py --emit-receipt
```

The verifier fails closed if any representative class bypasses an owner gate, collapses policy,
projects false terminal liveness, mutates during doctor mode, or cannot bind the receipt to exact
repository and policy evidence.

## Why This Matters

Locally correct adapters can still disagree at their seams. The final receipt proves the capability
as one governed flow and prevents owner docs from claiming support based only on component tests.

## Acceptance Criteria

- [ ] Every production adapter preserves its owner-native authority and no shared kernel or receipt
      becomes a second artifact registry or policy store.
      Verify: `tests/archival/test_cross_class_conformance.py::test_cross_class_adapters_preserve_owner_authority`
- [ ] Raw evidence, retained source, HKA recovery, and derivative disposition retain distinct policy
      profiles and terminal outcomes throughout the matrix.
      Verify: `tests/archival/test_cross_class_conformance.py::test_source_and_hka_policy_profiles_do_not_collapse`
- [ ] Restore failure, stale generation, conflict, revocation, and cleanup failure remain loud and
      non-terminal until the owner-native operation converges.
      Verify: `tests/archival/test_cross_class_conformance.py::test_restore_partial_failure_and_liveness_matrix`
- [ ] The doctor detects orphaned representations, missing source/recipe evidence, and pending
      cleanup without mutating bytes, receipts, classifications, or owner state.
      Verify: `tests/archival/test_cross_class_conformance.py::test_cross_class_doctor_detects_orphans_without_mutation`
- [ ] A durable redacted receipt binds exact SHA, matrix cases, adapter/policy versions, outcomes,
      and unresolved findings and is posted/read back on the parent Issue.
      Verify: runtime receipt: governed-archival-validation.v1
- [ ] The child provides a parent-closure and owner-doc-promotion handoff only after every child is
      terminal and the validation receipt is successfully read back.
      Verify: runtime receipt: builderops.epic-delivery-ledger.v1

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_cross_class_conformance.py`
2. `pytest -q tests/archival`
3. `pytest -q tests/heimdal/test_local_archive.py tests/heimdal/test_local_archive_retention.py`
4. `python3 scripts/verify_governed_archival_flow.py --emit-receipt`
5. Validate the receipt schema and exact-SHA binding, then read it back from the parent Issue before
   parent closure or owner-doc promotion.

## Out of Scope

- Adding artifact classes, changing adapter policy, repairing defects found by the verifier in this
  same Issue, closing the parent before readback, or claiming a cloud/off-site durability tier.
- Replacing the normal child PR review/verification gates.

## Restart / Durability Posture

Individual test processes are disposable. The final receipt is durable and exact-SHA-bound; partial
or interrupted validation has no acceptance authority and must restart from authoritative adapter
state. Parent acceptance remains pending until the complete receipt is posted and read back.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/GOVERNED_ARCHIVAL_FLOW/PARENT_FEATURE_ISSUE.md`
- `docs/testing/invariant-tests.md`
- `docs/EVENTS.md`
- `docs/HEIMDAL_LOCAL_ARCHIVE/README.md`

## Related GitHub Issues

Final bounded validation Issue. Execution context: `fresh_issue_agent`; helper budget `0`. TCD hint:
Terra / high because it integrates multiple already-delivered adapters and durable evidence but does
not design a new mechanism. Its terminal receipt hands parent acceptance to
`verification-and-closure`.
