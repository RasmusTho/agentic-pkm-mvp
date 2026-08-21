# HAR-04 cold-erasure mechanism convergence packet

Mechanism key: `heimdal.raw_liveness.pg_cold_erasure.v2`

Protected invariant: a governed erase either leaves the durable identity and every active
representation readable, or commits the tombstone/receipt and identity erasure before external
cold objects are removed; a cleanup failure remains retryable without restoring deleted authority.

## States and transitions

- `active`: raw identity and exactly one active representation exist; cold bytes resolve through
  the verified archive-root binding.
- `deletion_claimed`: retention claim exists and leases have drained; no identity mutation yet.
- `erasure_prepared`: deletion receipt/tombstone are staged, cold `location_ref`s are captured under
  the raw-record and representation row locks, and opaque refs are stored in receipt payload.
- `db_erased_pending_cold_cleanup`: representation and identity deletes committed; receipt payload
  remains the durable cleanup queue.
- `erased`: tombstone is durable and receipt cleanup queue is empty.
- `cleanup_pending`: DB erasure is terminal, but one or more external objects remain; retrying the
  same governed operation reconciles the receipt queue and never recreates identity/authority.

Allowed writers are `governed_delete_raw_record` / `_governed_delete_pg` for PG and the matching
memory governed path. Ordinary representation registration cannot delete identity or tombstone.

## Crash and durability ordering

1. Verify liveness fence, retention claim, lease drain, and raw-record lock.
2. Insert receipt and tombstone; capture opaque cold refs under `FOR UPDATE`; update receipt payload
   with those refs before any DB deletion.
3. Delete representations and identity; commit the DB transaction. Any failure before commit rolls
   back and external bytes are untouched.
4. Delete object/manifest after commit. Failure leaves a durable receipt queue (`cleanup_pending`).
5. A later `already_erased` retry reads the receipt queue and removes only resolved opaque refs;
   it fails closed if the archive-root resolver is unavailable.

## Producers, consumers, locks, and races

- HAR-03 verified-volume startup and HAR-04 relocation bind `HEIMDAL_ARCHIVE_ROOT` only after the
  proof validates encryption, mount identity, archive id, and exact mountpoint.
- Raw read gate consumes the active representation and resolver; it never infers authority from a
  filesystem object alone.
- PG deletion locks the content fence, generation, raw record, then cold representation rows.
  Cold registration locks the same raw record, so registration cannot commit after capture.
- Receipt retry is the queued consumer. It is idempotent (`missing_ok=True`) and does not reinsert
  rows. The PG receipt payload is atomically reduced to an empty ref list after successful
  reconciliation; the memory writer follows the same post-authority-delete ordering and keeps its
  receipt queue on cleanup failure. Stale observations cannot authorize deletion because the
  receipt/tombstone and row locks are the authority.

## Prior findings and proof map

HAR04-01..04: arbitrary mount proof, exception/path leakage, PG cleanup race, and memory-only
coverage. Subsequent adjacent P1s: forged/unbound archive root, mkdir/callback/manifest exception
context, process-restart root binding, rollback-unsafe external delete, and non-retryable
post-commit cleanup. The current implementation addresses each under the same mechanism key.

Focused proof: `tests/heimdal/test_local_archive.py` covers eligibility, proof/root mismatch,
receipt ordering, cache-loss re-resolution, callback/mkdir/manifest redaction, cursor locking,
post-commit receipt reconciliation and queue clearing, memory rollback ordering, and object/manifest
cleanup. `tests/heimdal/test_raw_liveness.py`
and `tests/heimdal/test_raw_store.py` cover governed liveness and representation contracts.
Migration convergence is covered by
`tests/migrations/test_heimdal_raw_representation_migration.py`, whose shape comparison targets
current head `d1a4b7c9e2f0` while historical HAR-02 tests remain at `e7b4c9d2a6f1`.
