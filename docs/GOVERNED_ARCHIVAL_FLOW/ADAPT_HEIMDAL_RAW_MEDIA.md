---
name: Adapt Heimdal Raw Media
description: Bind delivered HAR-01..05 raw representation, gated read, restore, retention, revocation, and liveness behavior to the governed archival contract for every admitted media modality
task_id: GAF-03
github_issue: 5065
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Current-Main Reconciliation"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-02]
depends_on: [IMPLEMENT_VERIFIED_TRANSITION_KERNEL.md]
can_parallelize_with: []
---

# Adapt Heimdal Raw Media

## Purpose

Make the delivered Heimdal mechanism the first production adapter and prove that its modality-neutral
raw store safely covers admitted audio, image, video, and document bytes without weakening HAR.

## What This Task Does

- Implement `app.archival.adapters.heimdal` as a thin mapping over existing raw identity,
  representations, archive receipts, read gate, consent/retention authority, cleanup queue, and
  liveness projection.
- Wire the production `heimdal archive-eligible` and restore paths through the shared transition
  contract at one mechanical boundary, retaining the existing HAR implementation as owner-native
  state authority.
- Add a four-modality production-path conformance matrix using the real media-ingress, archive,
  gated-read, restore, retention, and consent-revocation entrypoints.
- Preserve all HAR-01..05 tests, CLI receipts, archive-volume checks, lock ordering, migrations, and
  error vocabulary.
- Reconcile owner docs so raw media breadth is explicit without claiming a general retained-source or
  HKA archive.

## Concretely

```bash
pytest -q tests/archival/test_heimdal_adapter.py
pytest -q tests/heimdal/test_local_archive.py tests/heimdal/test_local_archive_retention.py
```

Each modality is admitted through `app.heimdal.media_ingress`, archived from the registered hot
representation, restored through `app.heimdal.raw_read_gate`, and retired through the delivered
HAR-05 liveness/cleanup path.

## Why This Matters

The current code is broader than its raw-audio documentation. An explicit adapter converts that
implicit breadth into tested, bounded behavior while retaining the hard-won HAR safety mechanism.

## Acceptance Criteria

- [x] Audio, image, video, and document captures traverse the real media-ingress and production
      archive entrypoint and preserve capture/content identity through cold activation.
      Verify: `tests/archival/test_heimdal_adapter.py::test_all_admitted_raw_modalities_conform_to_archive_contract`
- [x] Every modality restores through the existing raw-read gate and emits the existing redacted
      read/restore receipts; direct backend access remains unauthorized.
      Verify: `tests/archival/test_heimdal_adapter.py::test_raw_media_restore_reuses_production_gated_read`
- [x] Hard retention and consent revocation keep `erasure_pending` while cold cleanup remains and
      reach `erased` only after all registered bytes/manifests are gone.
      Verify: `tests/archival/test_heimdal_adapter.py::test_raw_media_revocation_preserves_har05_liveness_for_every_modality`
- [x] The adapter delegates owner-native state to Heimdal and creates no second raw identity,
      representation registry, cleanup queue, or receipt store.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_heimdal_adapter_has_no_parallel_authority_store`
- [x] Existing HAR-01..05 focused suites remain green without weakening their assertions.
      Verify: `tests/heimdal/test_local_archive_retention.py::test_restore_then_delete_all_raw_copies`
- [x] Current owner docs distinguish delivered raw-media archival breadth from the still-target-state
      cross-class capability.
      Verify: doc writeback at `docs/EVENTS.md :: Heimdal local archive restore + all-copy expiry`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_heimdal_adapter.py`
2. `pytest -q tests/heimdal/test_local_archive.py tests/heimdal/test_local_archive_retention.py`
3. `pytest -q tests/heimdal/test_media_ingress.py tests/heimdal/test_raw_liveness.py`
4. Run the selected PostgreSQL migration/contract lane named by `scripts/select_pr_tests.py`.
5. `ruff check app/archival app/heimdal tests/archival tests/heimdal`

## Out of Scope

- Reopening #3842 or HAR-01..05, changing raw retention/consent duration, migrating archive storage,
  or claiming curated retained-source/HKA support.
- Adding another raw store, archive volume, receipt store, or cleanup mechanism.

## Restart / Durability Posture

All authority remains in delivered Heimdal Postgres/memory test stores, manifests, receipts, and
durable cleanup state. The adapter holds no progress authority. Restart behavior remains HAR-05:
pending cleanup/revocation replays and cannot surface terminal erasure until convergence.

## Related Docs

- `docs/HEIMDAL_LOCAL_ARCHIVE/README.md`
- `docs/HEIMDAL_LOCAL_ARCHIVE/PROVE_RESTORE_AND_EXPIRY.md`
- `docs/EVENTS.md :: Heimdal local archive restore + all-copy expiry`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Media capture`
- Closed parent #3842 and children #3847–#3851

## Related GitHub Issues

One bounded adapter Issue; it extends delivered HAR behavior and does not supersede its Issues.
Execution context: `fresh_issue_agent`; helper budget `1` for an independent state-machine review.
TCD hint: Sol / high due protected raw data, migration compatibility, liveness, and concurrent
retention/revocation risk.
