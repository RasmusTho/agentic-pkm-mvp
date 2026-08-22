---
name: Prove Restore And Expiry
task_id: HAR-05
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Cross-task invariants
parent_capability: Heimdal Local Archive
prerequisites: [HAR-04]
depends_on: [HAR-04]
can_parallelize_with: []
---

State: Delivered task specification (HAR-05 implementation; parent real-channel acceptance pending)

# Prove Restore And Expiry

## Purpose

Close the archive safety loop: an authorized raw read must work from cold storage, while consent
revocation and hard retention still erase every raw copy with a durable receipt.

## What this task does

1. Extend the existing gated raw-read path to locate an archived record without widening its
   allowlist/receipt authorization.
2. Prove a bounded restore drill against an archived fixture/record and record only redacted evidence.
3. Traverse cold manifests during consent revocation and hard-retention enforcement, deleting cold
   bytes and manifest state together with a location-aware but content-redacted receipt.
4. Prove partial failures fail loud and do not report deletion complete while any raw copy remains.
5. Reconcile pre-HAR-05 cold rows only through an explicit verified-volume path: bound rows are
   retained during migration, while archive bytes, manifest identity, ciphertext hash, and raw
   identity must all be proven before the archive generation is activated. Unbound or mismatched
   rows remain fail-closed.
   A legacy cold row with an active pre-HAR-05 retention claim fails the migration preflight and
   must be drained under the old governed path before retrying the upgrade.
6. Mark migrated consent associations whose pre-HAR-05 duplicate-grant lineage cannot be proven as
   ambiguous; revocation conservatively selects those generations for governed erasure rather than
   claiming a grant-specific result that the historical data cannot support.

## Acceptance criteria

- [x] An authorized raw read resolves an archived record and emits the existing read receipt; an
      unauthorized read remains rejected.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_archived_read_reuses_gated_read_path`
- [x] A redacted restore drill proves archived bytes match their raw-record identity.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_restore_drill_proves_archived_identity`
- [x] Hard retention and consent revocation remove hot/cold copies and manifests atomically enough to
      never report complete while a location remains.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_restore_then_delete_all_raw_copies`
- [x] A cold-delete failure fails loud and leaves retryable receipt/state rather than silently
      claiming erasure.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_cold_delete_failure_is_loud_and_retryable`
- [x] A bound HAR-04 cold row survives upgrade as legacy metadata and becomes active only after
      explicit archive reconciliation verifies the mounted object and manifest identity.
      Verify: `tests/migrations/test_heimdal_raw_representation_migration.py::test_current_upgrade_preserves_bound_har04_cold_row_until_verified_reconciliation`

## Out of scope

Retention-duration changes, indefinite archive retention, un-gated browsing, and off-site copies.

## How to verify

`pytest -q tests/heimdal/test_local_archive_retention.py`
