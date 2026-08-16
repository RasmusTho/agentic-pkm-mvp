---
name: Project Approved Profile To Same-Scope Consumers
description: Expose only approved receipt-bound profile versions to same-scope consumers with explicit no-profile behavior.
task_id: GOVPROF-03
github_issue: 4947
source_anchor: "docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25"
parent_capability: Governed Vault Profile
prerequisites: [GOVPROF-02]
depends_on: [GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md]
can_parallelize_with: []
---

# Project Approved Profile To Same-Scope Consumers

## Purpose

Provide the narrow rebuildable consumer-read seam that D4 requires while preserving the ProfileAgent authority boundary and explicit absence behavior.

## What This Task Does

Build a local-first projection from approved ProfileAgent-written versions and their terminal receipts. A consumer may use it only when scope matches and all approval/version/receipt checks hold; otherwise it renders or returns an explicit no-profile state and does not infer, broaden, mutate, or consume pending material.

## Concretely

`pytest -q tests/governance/test_governed_vault_profile_consumer_projection.py` proves #4117's eventual overlay consumer receives only same-scope approved versions, produces no-profile behavior for every non-consumable condition, and can rebuild the projection from approved versions plus receipts.

## Why This Matters

Consumer convenience must not become a second writer, an implicit approval path, or a way to launder stale/pending profile data into runtime context.

## Acceptance Criteria

- [ ] The local-first consumer projection is rebuildable from approved profile versions and terminal receipts and never writes profile content.
  - Verify: `tests/governance/test_governed_vault_profile_consumer_projection.py::test_projection_rebuilds_only_from_approved_versions_and_receipts`
- [ ] Consumers admit only ProfileAgent-written, owner-approved, receipt-bound versions with matching scope.
  - Verify: `tests/governance/test_governed_vault_profile_consumer_projection.py::test_consumer_admission_requires_same_scope_approved_receipt_bound_version`
- [ ] Missing, pending, stale, unreceipted, or out-of-scope material yields explicit no-profile behavior without inference or fallback content.
  - Verify: `tests/governance/test_governed_vault_profile_consumer_projection.py::test_nonconsumable_profile_states_return_explicit_no_profile`
- [ ] The #4117 integration reads only this governed seam and does not create or mutate profile material.
  - Verify: `tests/governance/test_governed_vault_profile_consumer_projection.py::test_youtube_overlay_is_read_only_consumer_of_governed_profile_projection`

## How to Verify (Pre-Merge)

- `pytest -q tests/governance/test_governed_vault_profile_consumer_projection.py`
- Run the #4117 integration-equivalent no-profile and same-scope admission cases.

## Out of Scope

- Creating a profile, ProfileAgent writes, profile inference, egress, or changes to YouTube synthesis/bundle/quality behavior.

## Restart / Durability Posture

The projection is rebuildable and therefore may be discarded/rebuilt. Consumers do not retain an in-memory approval cache across restart; on unavailable proof they return explicit no-profile behavior.

## Related Docs

- `docs/GOVERNED_VAULT_PROFILE/README.md`
- `docs/YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY.md :: Contract`

## Related GitHub Issues

Parent: #4944
