---
name: Retain Originals Until Backend Receipt
description: Bifrost durable transfer outbox that keeps every captured original until the hub's durable-acceptance receipt is persisted locally, with idempotent resend and disk-rebuilt state.
task_id: CDLM-03
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-01]
depends_on: [ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md]
can_parallelize_with: [TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md]
---

# Retain Originals Until Backend Receipt

## Purpose

Close the loss window B3 shipped with: today the client deletes its original after *placement* in
the watched folder, and #4369 proved placement can be a black hole. Under this task the only event
that releases an original is the hub's durable-acceptance receipt, persisted on the device.

## What This Task Does

Builds the durable transfer outbox in the Bifrost client (`RasmusTho/bifrost`, Heimdal module
boundary per INV-B3-6):

- **Outbox item = original + envelope.** At capture finalization the item is written to an
  on-disk outbox store: the media file plus an envelope `{capture_id (minted exactly once here),
  content_sha256, kind, captured_at, device_id, session refs when present, state}`. Identity is
  minted before any send and never re-minted — the idempotency half the hub relies on
  (INV-CDLM-3).
- **Transfer loop.** Items send to `POST /api/heimdal/capture/media` when the hub is reachable
  (loopback/LAN/tailnet only). On a 2xx, the receipt is persisted into the item's envelope
  *before* any deletion is considered. On timeout or lost response, recovery queries
  `GET /api/heimdal/capture/receipts?capture_id=…` first and resends only true unknowns — resend
  is always safe, duplicate-free by the hub's contract.
- **Receipt-gated release.** Deleting the original requires `state = backend durably received`
  with the persisted receipt. The receipt record outlives the original. No other code path
  deletes outbox media — including failure paths, storage-pressure paths, and app upgrades.
- **Disk-rebuilt truth.** Relaunch rebuilds the queue exclusively from the outbox store; no
  in-memory state is authoritative. A crash between send and receipt persistence resolves through
  the receipt query, never through guessing.
- **Offline posture.** Unreachable hub means items stay `pending locally` indefinitely and
  visibly. The outbox never falls back to the watched folder; the legacy Model-1 lane remains a
  separate, explicitly non-receipt-gated path (README supersessions).
- **B3 composition.** Audio segments from HCAP-02/06 (iPhone recorder, Watch relay) route into
  this outbox. This supersedes HCAP-03's delete-after-placement for everything the outbox
  carries; the HCAP-03 watched-folder writer remains only as the legacy floor behind an explicit
  setting, default off on outbox-capable builds.

## Concretely

Simulator walk: capture a memo with the hub stopped → item visible as `pending locally`; force-quit
and relaunch → item still there, original intact; start the hub → item transitions
`transferring → backend durably received`; kill the app between the hub's 2xx and receipt
persistence (test seam) → relaunch resolves via receipt query without re-uploading bytes; only
then is the original eligible for deletion, receipt retained.

## Why This Matters

INV-CDLM-2 is the vertical's core trust promise: nothing the user captured is ever lost by the
transfer machinery. Every failure #4369/#4362 exposed — silent non-delivery, crash-looping
watchers, unknowable placement — becomes a visible `pending locally` item with its original safe
on device.

## Acceptance Criteria

- [ ] An original is deleted only after its durable-acceptance receipt is persisted in the outbox
  store, asserted at the production deletion call site (no other deletion path exists for outbox
  media).
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testDeletionRequiresPersistedReceipt`
- [ ] `capture_id` is minted exactly once at finalization and survives relaunch; a resend after
  simulated lost response reuses it and persists the hub's `idempotent_replay` receipt without
  duplicating the item.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testIdentityStableAcrossRelaunchAndResend`
- [ ] The queue rebuilds from disk alone after force-quit at each state (`pending locally`,
  `transferring`, post-2xx pre-persist), with no lost original and no fabricated advanced state.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testQueueRebuildsFromDiskAtEveryState`
- [ ] Recovery after an ambiguous send queries receipts first and resends only unknowns.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testRecoveryQueriesReceiptsBeforeResend`
- [ ] An unreachable hub leaves items `pending locally` with originals intact; no watched-folder
  fallback occurs from the outbox path.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testOfflineRetainsWithoutFolderFallback`
- [ ] Watch-relayed recordings (HCAP-06 path) enter the outbox and inherit all of the above.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferOutboxTests.swift::testWatchRelayEntersOutbox`

## How to Verify (Pre-Merge)

- bifrost CI runs the named XCTest targets on the iPhone destination. **Execution gate G-CI:**
  bifrost#52 (CI runs the wrong scheme and masks xcodebuild failures) must be fixed first, or the
  PR attaches local `xcodebuild test -only-testing:YggdrasilTests/TransferOutboxTests` output.
- `swiftlint --strict` clean per bifrost conventions.

## Out of Scope

- New capture modalities (CDLM-04). Queue UI (CDLM-05). Meeting UI (CDLM-09).
- Hub-side behavior of any kind (CDLM-01/02 own it).
- Storage-pressure eviction policy beyond "never evict un-receipted originals" (a future bounded
  slice if needed).
- Removing the legacy Model-1 writer (kept as the explicit phoneless/legacy floor).

## Restart / Durability Posture

Everything user-facing here survives restart by construction: outbox items, envelopes, states, and
receipts are on-disk; relaunch rebuilds the queue from disk alone. The one deliberately
non-durable thing is the in-flight transfer attempt itself — after a crash mid-send the item shows
`pending locally`/`transferring` again and recovery re-resolves via the receipt query. The user
may see a state *regress to truth* after relaunch (e.g. `transferring` back to `pending locally`);
they never see a fabricated `backend durably received`, and no original is ever gone without its
persisted receipt.

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-2/3/4; partial-failure matrix)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md` (the receipt contract)
- `docs/HEIMDAL_CAPTURE_CLIENT/DELIVER_RECORDINGS_TO_WATCHED_FOLDER.md` (superseded deletion semantics)
- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-1/5/6 — composed, not replaced)

## Related GitHub Issues

One bifrost issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT").
TCD hint: Opus / high — durability state machine with crash-window correctness; the
post-2xx-pre-persist window and the no-other-deletion-path assertion are the hard parts.
