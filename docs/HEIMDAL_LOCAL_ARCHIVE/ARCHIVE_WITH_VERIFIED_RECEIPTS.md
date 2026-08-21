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

## Out of scope

Changing retention duration, archive restore UX, cloud replication, or provider/model routing.

## How to verify

`pytest -q tests/heimdal/test_local_archive.py`
