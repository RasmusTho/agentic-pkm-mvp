---
name: Define Location-Aware Raw-Store Migration
task_id: HAR-02
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Cross-task invariants
parent_capability: Heimdal Local Archive
prerequisites: [HAR-01]
depends_on: [HAR-01]
can_parallelize_with: []
---

State: Authored task specification (future-state; child issue not yet filed)

# Define Location-Aware Raw-Store Migration

## Purpose

The current `heimdal_raw_record` stores ciphertext/nonce in an immutable Postgres row, and the gated
read path resolves `raw_ref` through that row. Deleting it to free the hot tier would make the
reference declared-absent and bypass all-copy retention. Define the location-aware storage evolution
before any cold-volume or copy work.

## What this task does

1. Separate immutable raw-record identity/provenance from ciphertext location through a
   migration-owned location/representation contract. A hot record can move to cold storage without
   changing its record id, `content_identity`, consent/provenance, or opaque `raw_ref`.
2. Evolve `raw_read_gate.read_raw_record` to resolve an authorized record through its active
   registered representation, never through an unchecked filesystem path.
3. Evolve retention/revocation so governed deletion removes every registered representation before a
   durable deletion receipt reports success. A relocation is not a hard deletion.
4. Include migration/backfill and fail-loud handling for legacy Postgres-backed records; preserve the
   append-only rule by adding a location layer rather than updating provenance in place.

## Acceptance criteria

- [ ] A migrated record retains the same opaque `raw_ref`, provenance, consent reference, and
      `content_identity` before and after hot-to-cold relocation.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_relocation_preserves_raw_ref_and_gated_read`
- [ ] The production raw-read gate retrieves only an active registered representation after its
      authorization/receipt checks; an arbitrary archive path cannot be supplied.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_raw_read_gate_resolves_registered_location_only`
- [ ] Hard retention and consent revocation enumerate every representation and do not emit success
      while hot or cold bytes remain.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_all_copy_deletion_is_required_before_receipt`
- [ ] Existing Postgres-backed raw records remain readable and migration/backfill failure is loud,
      resumable, and does not fabricate a cold locator.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_legacy_hot_records_remain_readable_during_migration`

## Out of scope

Creating/mounting an external volume, moving a live record, changing retention duration, or exposing
a general raw-file API.

## How to verify

`pytest -q tests/heimdal/test_local_archive_migration.py`
