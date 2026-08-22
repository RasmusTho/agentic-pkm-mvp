# HAR-04 cold-erasure mechanism convergence packet

State: Advisory mechanism-review evidence for Issue #3850 and PR #5035; not runtime authority.

Mechanism keys: `heimdal.local_archive.relocation_pass.v1` and
`heimdal.raw_liveness.pg_cold_erasure.v2`

Protected invariant: a governed erase either leaves the durable identity and every active
representation readable, or commits the tombstone/receipt and identity erasure before external
cold objects are removed; a cleanup failure remains retryable without restoring deleted authority.
The producer side admits exactly one bounded pass per raw-store authority: an unsuccessful copy,
verification, manifest, registration, or activation leaves the hot generation active and retryable.
No record-scoped external object may exist before an inactive durable representation gives retention
its opaque cleanup authority. Every cold location ref is bound to the producing archive identity by
an opaque digest; it resolves only while that same identity is backed by a fresh verified-volume
capability, regardless of which other valid archive root the process later binds.

## States and transitions

- `active`: raw identity and exactly one active representation exist; cold bytes resolve through
  the verified archive-root binding.
- `hot_archive_eligible`: the active representation is `postgres_hot` and record age is strictly
  between seven days and the configured retention boundary.
- `relocation_reserved`: the exact liveness generation is fenced against retention, one inactive
  cold representation durably owns its opaque location, and no record object has yet been written.
- `relocation_in_progress`: the same generation fence remains held while the reserved object is
  copied/fsynced, verified, receipted, and activated. The cold representation remains inactive
  until every external proof is durable.
- `cold_active`: copied bytes and content identity verified, manifest durable, cold representation
  registered, and activation atomically retired only the hot representation. A later pass omits it.
- `deletion_claimed`: retention claim exists and leases have drained; no identity mutation yet.
- `erasure_prepared`: cold `location_ref`s are captured under the raw-record and representation row
  locks, then the deletion receipt is inserted with the complete opaque cleanup queue and the
  tombstone is staged in the same transaction.
- `db_erased_pending_cold_cleanup`: representation and identity deletes committed; receipt payload
  remains the durable cleanup queue.
- `erased`: tombstone is durable and receipt cleanup queue is empty.
- `cleanup_pending`: DB erasure is terminal, but one or more external objects remain; retrying the
  same governed operation reconciles the receipt queue and never recreates identity/authority.

Allowed writers are `governed_delete_raw_record` / `_governed_delete_pg` for PG and the matching
memory governed path. `run_archive_pass` is the production relocation producer and may only call
`relocate_raw_record` while holding `archive_relocation_lease`. Ordinary representation registration
cannot delete identity or tombstone.

## Crash and durability ordering

Relocation producer:

1. Acquire the raw-store relocation lease (non-blocking memory lock or PostgreSQL session advisory
   lock). A second scheduler process returns `archive_pass_already_running` before metadata, volume,
   or record access.
2. Resolve channel-governed archive metadata and verify/bind the encrypted volume. Resolve the
   settings-governed retention window, select only active-hot eligible records, and bound the batch.
3. Revalidate the volume for each item, acquire the exact generation's shared relocation/retention
   fence plus the verified archive-volume mutation lock, verify that hot is still active, and
   durably register one inactive cold reservation before the first object byte is written. Retry
   reuses the sole matching pending reservation and fails closed on duplicate or malformed pending
   state.
4. While retaining that fence, copy/fsync ciphertext, verify bytes and immutable content identity,
   fsync the redacted manifest, then atomically activate cold and retire hot. An ordinary
   pre-activation failure removes object/manifest best-effort but retains the inactive reservation,
   so retry and retention keep cleanup authority. An activation call with an ambiguous commit
   preserves verified artifacts rather than risking removal of the newly active copy.
5. Process loss releases both fences. A crash after reservation or external write leaves a
   discoverable inactive representation: retention captures its opaque ref, while relocation
   replay overwrites/reverifies the same reserved object. A replay skips already-cold records and
   retries only records whose hot representation remains active. If only the PostgreSQL fence
   connection is lost while its process continues, the OS lock remains held and post-commit cleanup
   cannot clear the queue while that process still holds the archive-volume mutation lock; cleanup
   remains pending until the writer exits the critical section.

Erasure consumer:

1. Verify liveness fence, retention claim, lease drain, and raw-record lock.
2. Capture opaque cold refs under `FOR UPDATE`, insert the receipt with that complete queue, then
   insert the tombstone before any DB deletion. The queue is never grown through an UPDATE; its
   payload key is reserved from caller input.
3. Delete representations and identity; commit the DB transaction. Any failure before commit rolls
   back and external bytes are untouched.
4. Delete object/manifest after commit. Each successful deletion is removed from the durable
   receipt queue before the next deletion; failure leaves the reduced queue durable and the state
   `cleanup_pending`.
   Relocation cannot write an object before representation registration. A registration failure
   therefore discards only its process-local location binding; once registration commits, the
   inactive row remains the durable retry and cleanup authority even if object creation fails.
5. A later `already_erased` retry reads the receipt queue and removes only resolved opaque refs;
   it fails closed if the archive-root resolver is unavailable or is verified for a different
   archive identity. The mismatched ref remains queued, and rebinding the producing archive resumes
   cleanup without rewriting authority.

## Producers, consumers, locks, and races

- HAR-03 verified-volume startup and HAR-04 relocation bind `HEIMDAL_ARCHIVE_ROOT` only after the
  proof validates encryption, mount identity, archive id, and exact mountpoint.
- The serving process performs the same verified-volume startup binding in its API lifespan after
  restart and explicitly reapplies the returned capability to its process-local resolver;
  `HEIMDAL_ARCHIVE_ROOT` alone is never a resolver authority and cold reads fail closed until that
  binding exists.
- The repository-owned `heimdal archive-eligible` CLI invokes `run_archive_pass`; external schedule
  overlap is rejected by the memory/PostgreSQL relocation lease before volume or record access.
  Volume readiness is revalidated for every selected item, and receipts contain no identities or
  filesystem paths.
- Cold location binding, archive-root configuration, and cold representation registration all
  require the same issuer-gated `ArchiveVolumeReady` capability; direct raw-store calls cannot
  place or activate a cold copy under an arbitrary local path. The persisted location syntax binds
  its object UUID to `sha256(archive_ref)`; PostgreSQL migration `f4b6c8d0e2a1` rejects historical
  unbound cold rows rather than guessing an archive, while runtime/bootstrap preflight verifies the
  exact CHECK semantics.
- Raw read gate consumes the active representation and resolver; it never infers authority from a
  filesystem object alone.
- Relocation and deletion take the same content fence and exact generation lock. Relocation holds
  it across reservation, object/manifest durability, and activation; deletion therefore either
  completes first (causing relocation's liveness assertion to fail before a write) or captures the
  already-durable cold reservation. Memory uses the shared re-entrant liveness fence; PostgreSQL
  uses the transaction advisory content lock followed by the generation row lock. PG deletion then
  locks the raw record and cold representation rows.
- External writes and post-authority deletes also share one verified archive-volume file lock.
  Relocation holds it from before reservation through activation. Cleanup acquires it non-blocking;
  a live or connection-orphaned writer therefore leaves the durable queue pending rather than
  allowing `missing_ok` to clear authority before a late write. A process crash releases the OS
  lock, and the next scheduled receipt retry converges.
- Receipt retry is the queued consumer. It is idempotent (`missing_ok=True`) and does not reinsert
  rows. The PG receipt payload is atomically reduced after each successful reconciliation (and is
  committed even when a later object fails), reaching an empty ref list only after all objects
  succeed. The memory writer follows the same post-authority-delete ordering and persists its
  reduced receipt queue on cleanup failure. The PG post-commit reconciliation reacquires the
  content fence before consuming the queue, so cleanup cannot race a new generation or
  registration. The scheduled retention writer scans active generations first so an in-flight
  response lease cannot invert the producer/retention fence handshake, then indexes pending cleanup from durable receipts,
  rather than active raw rows (which are already gone after DB erasure), and invokes the same
  governed retry path; failed external deletion remains queued for the next run. Stale
  observations cannot authorize deletion because the receipt/tombstone and row locks are the
  authority.
- PG schema preflight validates the reconciliation trigger function body, not just trigger name;
  it requires the guarded UPDATE return path, immutable-column equality, order-preserving
  monotonic removal-only queue progress, and rejecting exception path. The initial complete queue
  arrives in the receipt INSERT, so the trigger never needs a queue-growth exception.
  Partial/pre-e2f3 or semantically drifted schemas
  fail at the migration boundary before any erase state transition. The active runtime path does
  not accept the historical receipt trigger; that shape is recognized only by version-bounded
  migration tests.
- Ingress startup routes through the complete raw-store assertion, which in turn validates the
  liveness authority. It therefore requires the exact current `f4b6c8d0e2a1` archive-binding CHECK
  as well as the e2 cleanup trigger/helper before reporting either raw ingress lane available; an
  e2 database is a named degraded state and cannot defer this failure until the first read/erase.

## Prior findings and proof map

HAR04-01..04: arbitrary mount proof, exception/path leakage, PG cleanup race, and memory-only
coverage. Subsequent adjacent P1s: forged/unbound archive root, mkdir/callback/manifest exception
context, process-restart root binding, rollback-unsafe external delete, and non-retryable
post-commit cleanup. The current implementation addresses each under the same mechanism key.
The latest protected P1s (external cold bytes could precede registry authority while retention ran,
and a post-restart cleanup ref could be redirected to a different verified root) are bound to the
same mechanism and repaired by the durable reservation/shared generation fence plus archive-bound
opaque refs.

Focused proof: `tests/heimdal/test_local_archive.py` covers eligibility, proof/root mismatch,
bounded producer selection/replay/overlap, explicit startup rebinding, receipt ordering,
cache-loss re-resolution, two-root mismatch refusal/retry, callback/mkdir/manifest redaction,
cursor locking,
post-commit receipt reconciliation and queue clearing, per-object queue progress, registration
failure pre-write ordering, pending-reservation replay, memory relocation/retention interleaving and
process-loss cleanup, memory rollback ordering, and object/manifest cleanup.
`tests/heimdal/test_raw_liveness.py`
and `tests/heimdal/test_raw_store.py` cover governed liveness, representation contracts, and the
PostgreSQL cross-process scheduler lease. `tests/cli/test_heimdal_cli.py` covers the redacted
production command boundary.
Migration convergence is covered by
`tests/migrations/test_heimdal_raw_representation_migration.py`, whose shape comparison targets
current head `f4b6c8d0e2a1` while historical HAR-02 tests remain at `e7b4c9d2a6f1`; the same current-
head PG suite proves reservation-before-write, retention blocking, crash cleanup, queue durability
after simulated DB-fence loss, two-root cleanup authority, fail-loud rejection of unbound cold refs,
ingress refusal at the explicit e2/f4 boundary, and pre-e2f3 refusal before any erase transition.
