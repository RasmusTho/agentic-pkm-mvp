---
name: Archive With Verified Receipts
task_id: HAR-04
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Cross-task invariants
parent_capability: Heimdal Local Archive
prerequisites: [HAR-03]
depends_on: [HAR-03]
can_parallelize_with: []
---

State: HAR-04 runtime delivered; restore/expiry remains future-state under HAR-05

# Archive With Verified Receipts

## Purpose

Move an eligible raw record from hot to encrypted cold storage without weakening the raw store's
append-only/provenance/read-gate discipline or risking silent loss.

## What this task does

1. Select only records older than seven days and younger than the configured hard-retention boundary.
2. Copy the registered hot ciphertext representation and minimal lifecycle metadata to the mounted
   archive without changing the raw-record identity.
3. Verify copied bytes and content identity, commit an archive manifest/receipt, then use the
   location-aware migration to retire only the hot representation. The record and `raw_ref` remain
   resolvable through the gated read path.
4. Surface a retryable health failure when verification/mount/receipt persistence fails; retain the
   hot copy in every such case.
5. Expose `python -m app.cli heimdal archive-eligible` as the repository-owned, bounded one-shot
   producer for an external scheduler. Each pass is cross-process serialized, revalidates the
   channel-governed encrypted volume before every copy, and emits only counts plus reason codes.
6. Before the first record object byte is written, commit an inactive opaque-location reservation
   while holding the same generation fence as retention and the verified archive-volume mutation
   lock. The location ref carries an opaque digest of the producing archive identity, never a path;
   process or DB-fence loss must leave either no object or a durable, retryable cleanup ref.

## Acceptance criteria

- [x] Records are archive-eligible only after seven days and never after configured retention expiry.
      Verify: `tests/heimdal/test_local_archive.py::test_archive_eligibility_respects_hot_and_retention_bounds`
- [x] A successful archive writes a durable manifest/receipt binding original raw-record identity to a
      verified cold representation before hot retirement, with the same gated `raw_ref`.
      Verify: `tests/heimdal/test_local_archive.py::test_verified_archive_receipt_precedes_hot_retirement`
- [x] Checksum/content-identity mismatch, unavailable mount, or receipt failure keeps the hot copy and
      emits a loud degraded health result.
      Verify: `tests/heimdal/test_local_archive.py::test_verify_before_hot_representation_retire_and_fail_closed`
- [x] The archive path exposes no raw content or filesystem paths in receipts/logs.
      Verify: `tests/heimdal/test_local_archive.py::test_archive_receipts_are_redacted`
- [x] A bounded production pass selects eligible hot records, is safe to retry, and refuses an
      overlapping scheduler invocation before touching the volume or records.
      Verify: `tests/heimdal/test_local_archive.py::test_bounded_archive_pass_selects_and_relocates_eligible_hot_records`
      and `tests/heimdal/test_raw_store.py::test_archive_relocation_lease_serializes_postgres_scheduler_sessions`
- [x] Relocation cannot race retention into an unregistered or late-written orphan; memory and
      PostgreSQL prove reservation-before-write, shared-fence ordering, process-loss cleanup, and
      retryable cleanup when only the PG fence connection is lost.
      Verify: `tests/heimdal/test_local_archive.py::test_relocation_reservation_fences_retention_and_crash_cleanup`
      and `tests/migrations/test_heimdal_raw_representation_migration.py::test_pg_relocation_reservation_fences_retention_and_crash_cleanup`
      and `tests/migrations/test_heimdal_raw_representation_migration.py::test_pg_archive_lock_keeps_cleanup_retryable_if_db_fence_is_lost`
- [x] A cleanup ref resolves only under the same verified archive identity that produced it. A
      restart or rebind to another valid root leaves the original object and durable queue pending
      until the producing archive is verified again.
      Verify: `tests/heimdal/test_local_archive.py::test_cleanup_refuses_a_different_verified_archive_after_rebind`
      and `tests/migrations/test_heimdal_raw_representation_migration.py::test_pg_cleanup_refuses_a_different_verified_archive_after_rebind`

## Out of scope

Changing retention duration, archive restore UX, cloud replication, or provider/model routing.

## How to verify

`pytest -q tests/heimdal/test_local_archive.py tests/cli/test_heimdal_cli.py`
