---
name: Define Location-Aware Raw-Store Migration
task_id: HAR-02
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Cross-task invariants
parent_capability: Heimdal Local Archive
prerequisites: [HAR-01]
depends_on: [HAR-01]
can_parallelize_with: []
---

State: HAR-02 runtime/migration contract delivered; local cold archive remains future-state

# Define Location-Aware Raw-Store Migration

## Purpose

Before HAR-02, `heimdal_raw_record` stored ciphertext/nonce in the immutable Postgres identity row,
and the gated read path resolved `raw_ref` through that row. Deleting it to free the hot tier would
have made the reference declared-absent and bypassed all-copy retention. HAR-02 now supplies the
location-aware identity/representation contract required before any cold-volume or copy work.

## What this task does

1. Separate immutable raw-record identity/provenance from ciphertext location through a
   migration-owned location/representation contract. Changing the active registered representation
   preserves the record id, `content_identity`, consent/provenance, and opaque `raw_ref`; a later
   archive slice may use that invariant for a verified hot-to-cold move.
2. Evolve `raw_read_gate.read_raw_record` to resolve an authorized record through its active
   registered representation, never through an unchecked filesystem path. Initial insert,
   registration, activation, and gated read decrypt and verify representation plaintext against the
   immutable SHA-256 `content_identity`; mismatch refusal is atomic and emits no read receipt.
3. Evolve retention/revocation so governed deletion removes every registered representation before a
   durable deletion receipt reports success. A relocation is not a hard deletion.
4. Include migration/backfill and fail-loud handling for legacy Postgres-backed records; preserve the
   append-only rule by adding a location layer rather than updating provenance in place. Before any
   backfill mutation, the migration uses the configured raw-store key to decrypt each legacy copy and
   match it to the immutable `content_identity`; failure rolls back with the legacy schema and bytes
   intact for a corrected rerun.

## Acceptance criteria

- [x] A migrated record retains the same opaque `raw_ref`, provenance, consent reference, and
      `content_identity` when its active registered representation changes. This proves the identity
      invariant needed for later hot-to-cold relocation; HAR-02 does not perform a live cold move.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_relocation_preserves_raw_ref_and_gated_read`
- [x] The production raw-read gate retrieves only an active registered representation after its
      authorization/receipt checks; an arbitrary archive path cannot be supplied. It also refuses
      an active representation whose decrypted plaintext does not match the immutable
      `content_identity`, without returning plaintext or writing a receipt.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_raw_read_gate_resolves_registered_location_only`
- [x] Hard retention and the shared deletion primitive required by future consent revocation
      enumerate every representation and do not emit success
      while hot or cold bytes remain.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_all_copy_deletion_is_required_before_receipt`
- [x] Existing Postgres-backed raw records remain readable and migration/backfill failure is loud,
      resumable, and does not fabricate a cold locator.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_legacy_hot_records_remain_readable_during_migration`

## Out of scope

Creating/mounting an external volume, moving a live record, changing retention duration, or exposing
a general raw-file API.

## How to verify

`pytest -q tests/heimdal/test_local_archive_migration.py`
