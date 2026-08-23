State: Specification directory (design + bounded slices). HAR-01 through HAR-05 and the GAF-03 raw-media adapter are delivered; parent real-channel acceptance remains pending. Defines a local, encrypted cold tier for admitted Heimdal raw media; it does not change the existing retention bound or claim cloud/off-site durability.
Doc role: Capability specification (feature-breakdown lane)
Authority: Owns the local raw-media archive design. Subordinate to `docs/HEIMDAL/OWNER_DECISIONS.md :: R-RETENTION`, `docs/HEIMDAL/FABLE_COMPANION.md` for the raw-store boundary, and `docs/EVENTS.md` for current raw-store behavior.
Owner: Architecture / product
Temporal class: strategic
Review cadence: event-driven (task merge, retention change, storage-device change, or restore drill)
Source of truth: this directory for the proposed capability; GitHub parent/child issues are execution artifacts once filed
Last reviewed: 2026-08-22

# Heimdal Local Archive

## Outcome

Keep admitted raw media (audio, image, video, and document originals) on the normal encrypted Heimdal hot store for the first **seven days**, then make a
verified cold copy on a locally attached external disk. The external disk hosts an **encrypted APFS
sparsebundle**; it is not reformatted, and raw media is never written directly to an unencrypted
volume or iCloud. The raw-store encryption key stays outside both the database and the archive volume
through Local Secret Provisioning.

This is Product/Runtime work in the Heimdal raw-evidence lifecycle, with a host/deploy boundary for
mounting the archive. Mimer receives only its normal minimized candidates/transcripts/provenance;
BuilderOps receives neither recordings nor product data.

## Fixed constraints

1. **Local only now.** No AWS, object store, or other cloud storage is introduced here.
2. **Two encryption layers.** Heimdal raw blobs remain encrypted with the raw-store key; the cold tier
   is also an encrypted APFS sparsebundle. Direct use of an unencrypted external volume is prohibited.
3. **Seven days is tiering, not retention extension.** The settings-driven hard-retention bound stays
   authoritative. At expiry or consent revocation, every raw copy — hot and cold — is removed with a
   durable receipt.
4. **Verify before retiring hot data.** A source item is eligible for hot-tier removal only after its
   archive copy, byte count/hash/content identity, metadata, and receipt are durable. Failed or
   unmounted archive storage leaves the hot copy intact and raises a loud health signal.
5. **Restore is required evidence.** An archive is not accepted merely because files exist; a bounded
   restore drill must prove an authorized raw read can recover an item and preserve provenance.
6. **Capacity is measured before sizing.** Capacity/rotation uses non-content aggregate capture volume,
   not a guessed quota.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | [Measure capture volume](MEASURE_CAPTURE_VOLUME.md) | HAR-01 | — | aggregate daily bytes/counts and capacity forecast, no content telemetry |
| 2 | [Define location-aware raw-store migration](DEFINE_LOCATION_AWARE_RAW_STORE.md) | HAR-02 | HAR-01 | preserves `raw_ref`, read gate, provenance and all-copy deletion during relocation |
| 3 | [Provision encrypted cold volume](PROVISION_ENCRYPTED_COLD_VOLUME.md) | HAR-03 | HSP-02, HAR-02 | delivered sparsebundle lifecycle with no disk reformat |
| 4 | [Archive with verified receipts](ARCHIVE_WITH_VERIFIED_RECEIPTS.md) | HAR-04 | HAR-03 | governed relocation, verified manifest and health |
| 5 | [Prove restore and expiry](PROVE_RESTORE_AND_EXPIRY.md) | HAR-05 | HAR-04 | restore drill plus hot/cold deletion at retention/revocation |

Flat order: **HAR-01 → HAR-02 → HAR-03 → HAR-04 → HAR-05**. This sequence is deliberate: raw-data retention
already enforces irreversible deletion.

## Cross-task invariants

- **INV-HAR-1 — raw media never enters iCloud as archive storage or an unencrypted external volume.**
  The existing accepted iCloud pre-seam capture inbox remains ingress only; archive writes target the
  mounted encrypted sparsebundle only.
- **INV-HAR-2 — archive is not an authority fork.** An archive manifest refers to the existing raw
  record/content identity and lifecycle state; it does not publish observations or create Mimer
  knowledge.
- **INV-HAR-2a — relocation preserves raw identity.** A relocation does not turn a live `raw_ref`
  into a dangling reference: record identity/provenance remains resolvable through the gated read path
  while a location-aware storage layer selects hot or cold ciphertext. Deleting the current immutable
  `heimdal_raw_record` is never a relocation shortcut.
- **INV-HAR-3 — no silent data loss.** Incomplete copy, checksum mismatch, unavailable mount, or
  missing receipt prevents hot retirement and surfaces health/debt evidence.
- **INV-HAR-4 — bounded retention deletes all raw copies.** Consent revocation and configured hard
  retention traverse hot and cold locations. Directory deletions become durable before the opaque
  cleanup queue advances, and no public receipt can mutate that authority. Every deletion reason
  preserves a redacted consent-grant correlation; append-only revocation rows are replayed by the
  scheduled retention path after a restart. Repeated cleanup failure raises before successful
  enforcement/freshness output, while public media receipt recovery remains on its existing 503
  unavailable contract until internal cleanup converges. A deletion receipt identifies record and
  locations without disclosing audio paths or content.
- **INV-HAR-5 — restore remains gated.** Cold archive access reuses the raw-read allowlist and receipt
  discipline and binds proof to the exact representation read under the shared fence; mounting an
  archive does not make raw media generally readable.

HAR-04's runtime producer is the bounded `python -m app.cli heimdal archive-eligible` pass. A host
scheduler may invoke it repeatedly; the pass serializes against another invocation through the raw
store, revalidates the channel-governed encrypted volume, and leaves every failed item hot for retry.
It commits an inactive opaque-location reservation before writing record bytes and holds both the
retention generation fence and verified archive-volume mutation lock through activation, so process
or DB-fence loss remains discoverable and cleanup-retryable. The opaque location includes a digest
binding to the producing archive identity (not a filesystem path), so a restart or valid rebind to
another root cannot redirect reads or consume pending cleanup. Its receipt contains aggregate
counts and closed reason codes only.

## Capability acceptance criteria

- [ ] Aggregate capture-volume evidence forecasts the seven-day hot tier and remaining retention
      window without collecting transcript/audio content.
      Verify: `tests/heimdal/test_archive_capacity.py::test_capacity_receipt_contains_aggregates_only`
- [ ] An archive mounts only through an encrypted sparsebundle and fails loud while absent or locked;
      the external disk is never reformatted by runtime.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_archive_requires_mounted_encrypted_volume`
- [ ] A hot-to-cold relocation preserves `raw_ref`, read-gate authorization, immutable provenance,
      and all-copy deletion semantics; no direct raw-record deletion acts as relocation.
      Verify: `tests/heimdal/test_local_archive_migration.py::test_relocation_preserves_raw_ref_and_gated_read`
- [x] Cold archival verifies identity/hash and a durable receipt before hot copy retirement; a forced
      verification failure retains the hot copy.
      Verify: `tests/heimdal/test_local_archive.py::test_verify_before_hot_representation_retire_and_fail_closed`
- [x] A raw item can be restored through the existing gated read path, and expiry/revocation removes
      both tiers with durable receipts.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_restore_then_delete_all_raw_copies`
- [ ] A real dev/test archive receipt establishes measured capacity, mounted encrypted storage, one
      restore, and one expiry/revocation traversal before parent acceptance.
      Verify: parent-issue validation receipt (redacted local dev/test channel)

## Validation and acceptance

Each child posts test evidence to the parent. Parent acceptance requires a redacted dev/test receipt
showing the encrypted volume mounted, one eligible recording relocated while retaining its gated
`raw_ref`, restored through that read path, an archive verification failure that kept the hot copy,
and a deletion traversal that removed all raw copies. Only then may owner docs describe local cold
archive as supported behavior.

## Out of scope

Changing the hard-retention duration, indefinite raw-media retention, cloud/off-site backup,
unencrypted external media, Mimer storage of audio, DB disaster recovery (#2965), key rotation, and
automatic external-drive purchases or replacement.

## Related sources

- `docs/HEIMDAL/OWNER_DECISIONS.md :: R-RETENTION / D-RETENTION`
- `docs/HEIMDAL/FABLE_COMPANION.md :: T1 / HEIM-7 / Voice-memo capture adapter`
- `docs/EVENTS.md :: Heimdal raw-evidence store + voice-memo capture adapter`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`
