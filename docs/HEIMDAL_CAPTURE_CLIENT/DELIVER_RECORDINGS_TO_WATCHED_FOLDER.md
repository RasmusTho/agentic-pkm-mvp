---
name: Deliver Recordings To Watched Folder
description: Move staged recordings into the bound watched folder with temp-name-then-rename completeness discipline, a visible pending queue, and delete-local only after confirmed placement.
task_id: HCAP-03
source_anchor: docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md :: Model 1
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-02]
depends_on: [DISCRETE_RECORD_WITH_BACKGROUND_AUDIO]
can_parallelize_with: [DEVICE_REGISTRATION_AND_CONSENT_SURFACE]
---

# Deliver Recordings To Watched Folder

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

Model 1 transport: the recording becomes hub property the moment it sits complete in the watched
iCloud folder. This task owns the staging → watched-folder hop and the accountability around it
(INV-B3-1). It replaces the stock-Voice-Memos + Shortcut hop with a first-party, disciplined
delivery.

## What This Task Does

- On segment `staged` (and on retry/app-launch reconciliation), copy the file into the bound
  capture folder via `NSFileCoordinator` coordinated write (correctness against the Files
  provider), **as a non-admissible temp name first** (e.g. `<name>.m4a.uploading` — the hub
  adapter's extension allowlist ignores it), then atomically rename to the final `.m4a` name.
  The hub's two-read stability guard (#3112) plus this discipline means the adapter can never
  admit a partial.
- Delete the staging copy **only after** the coordinated write + rename returns success
  (delete-after-confirmed-placement; the hub deletes the watched-folder copy after ITS confirmed
  raw-store write — each hop owns its own custody hand-off).
- Failures (unbound/stale folder, provider errors, disk full) keep the item in the queue with a
  visible error state and manual retry; automatic retry on next app activation. The queue is
  rebuilt from the staging directory on launch — no in-memory-only ledger.
- Queue UI in the Heimdal area: staged/delivering/delivered-awaiting-sync/failed, with per-item
  timestamps. "Delivered" means placed in the folder — iCloud sync progress and hub admission are
  outside the client's knowledge (JD/HCAP-08 observe those); the UI wording must not overclaim.

## Concretely

Simulator with a bound local folder: stop a recording → item flips staged→delivering→delivered;
the folder shows `heimdal-....m4a` (never a lingering `.uploading` on success); staging no longer
has the file. Kill the folder binding → next delivery fails visibly, file stays staged; rebind →
retry succeeds.

## Why This Matters

This hop is where a capture could silently die (half-synced file, deleted-before-placed, invisible
failure). The temp-name discipline composes with the hub's stability guard into an end-to-end
no-partial-ingest guarantee, and custody hand-off discipline makes "the app lost my memo"
structurally impossible to hide.

## Acceptance Criteria

- [ ] Delivery writes a temp-named file and atomically renames to the admissible final name; on
  any failure before rename, no admissible-named file exists in the folder. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CaptureDeliveryTests.swift::testTempNameThenRenameNeverExposesPartial`
  (new; injected failing copy mid-write).
- [ ] Staging copy is deleted only after confirmed placement; failure keeps it. `Verify:` bifrost
  `CaptureDeliveryTests.swift::testLocalDeleteOnlyAfterConfirmedPlacement` (new).
- [ ] Queue state is rebuilt from disk on relaunch (staged and failed items reappear). `Verify:`
  bifrost `CaptureDeliveryTests.swift::testQueueRebuiltFromStagingDirectory` (new).
- [ ] Delivery goes through coordinated file access on the production delivery path (enforcement
  AC). `Verify:` bifrost `CaptureDeliveryTests.swift::testDeliveryUsesCoordinatedWrite` (new;
  asserts the coordinator seam is exercised from the queue's deliver method).

## How to Verify (Pre-Merge)

- bifrost CI green; `swiftlint --strict` clean. Real iCloud sync behavior is not
  simulator-provable — HCAP-08 owns the real-runtime receipt.

## Out of Scope

- Streaming transport (Model 2 — only if EXP-1 fails Model 1; would be a new spec task).
- Sidecar metadata (HCAP-07 extends this delivery path).
- Hub-side admission/ASR behavior (hub-owned; HCAP-08 observes it).

## Restart / Durability Posture

Every queue state is derivable from disk (staging dir + folder presence); force-kill at any point
loses at most in-memory UI state, reconstructed on launch. The user-visible consequence of a
mid-delivery kill is an item back in `staged`/`failed`, never a lost or double-admitted memo
(hub-side idempotency by content hash absorbs re-delivery of an identical file).

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-1; transport model)
- Hub: `app/heimdal/capture_adapter.py` (allowlist, stability guard, delete-after-write) — read
  for interface understanding; not modified by this task.

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` on the HCAP-02
issue), linking hub #3026 and this spec file. TCD hint: Sonnet / high effort — file-custody
correctness with injected failures; the tests are the hard part, the code is small.
