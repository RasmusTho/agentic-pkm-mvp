---
name: Watch One-Tap Record With Haptic Status
description: watchOS companion — one-tap record, haptic feedback on pause/resume/stop, "still capturing?" glance, and WatchConnectivity file relay into the phone's delivery queue.
task_id: HCAP-06
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §2 Platform footprint (Apple Watch row)
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-03]
depends_on: [DELIVER_RECORDINGS_TO_WATCHED_FOLDER]
can_parallelize_with: [DEVICE_REGISTRATION_AND_CONSENT_SURFACE, DEVICE_HEALTH_PANEL_WITH_GAP_LOG]
---

# Watch One-Tap Record With Haptic Status

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

State: **Implemented.** Delivered by
[`RasmusTho/bifrost` PR #38](https://github.com/RasmusTho/bifrost/pull/38)
(issue #19, 2026-07-21). The implementation includes the shared admissible-media gate, durable
Watch/phone relay custody across callback and relaunch seams, truthful session metadata for the
HCAP-07 sidecar, and recorder-confirmed transition haptics. Physical-device WatchConnectivity
timing and haptic feel remain HCAP-09 walkthrough scope.

## Purpose

The Watch is a Heimdal surface only: "start a memo, feel a haptic when capture pauses/resumes,
glance at 'still capturing?'. No Mimer reading on the wrist." The study's interruption cases make
the haptic the point — the human must *feel* when capture stops without looking. Transport is
relay-only (INV-B3-5): no watchOS networking exists for anything else (Tailscale absent on
watchOS; streaming rejected as R-EXTERNAL).

## What This Task Does

- Adds a **watchOS app target** to the Xcode project (SwiftUI; paired to the Yggdrasil iOS app).
  CI must at minimum build it on every PR (extend the workflow with a watchOS simulator build
  step; scheme/destination pinning discipline per bifrost#8).
- Watch UI: one large record/stop button; while recording, elapsed time + a recording indicator
  (the "still capturing?" glance); recent-item count queued for relay.
- **Haptics** (`WKInterfaceDevice.play`): distinct patterns on record-start, pause (interruption),
  resume, stop/finalize, and relay-failure — the pause haptic is the study's core ask.
- Recording via watchOS `AVAudioRecorder` to a local `.m4a`; on stop, **relay** via
  `WCSession.transferFile` (queued, survives app suspension, delivers in background) to the
  iPhone app, which files it into the HCAP-03 staging queue (from there INV-B3-1's custody
  discipline owns it). Watch-side file deleted only on WC delivery confirmation
  (`didFinish file:error:` without error).
- Phoneless reality stated in-UI: if the phone is unreachable, recordings queue on the Watch with
  a visible count; native phoneless delivery is NOT claimed (stock Voice Memos on a cellular
  Watch remains the documented phoneless floor).

## Concretely

Paired simulators: tap record on Watch → speak → tap stop → haptic plays, file appears in the
iPhone app's staged queue → delivery proceeds per HCAP-03. Phone unreachable → item shows queued
on Watch; reachable again → WC delivers without user action.

## Why This Matters

One-tap wrist capture is the lowest-friction discrete capture the study identified — but only if
its custody chain is as accountable as the phone's. Relay-only keeps the Watch inside the
sanctioned transport envelope (no R-EXTERNAL surface) while haptics close the silent-interruption
trust gap.

## Acceptance Criteria

- [x] Watch target builds in CI (watchOS simulator destination). `Verify:` `.github/workflows/ci.yml`
  diff + green run on the PR head including the watch build step.
- [x] Relay custody: watch-side file is deleted only on confirmed WC delivery; failure keeps it
  queued and visible. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/WatchRelayCustodyTests.swift::{testDeleteOnlyOnConfirmedTransfer,testFailedTransferStaysQueued}`
  (new; WC session faked — the custody logic must be extracted testably).
- [x] Relayed files enter the same staging queue and delivery path as phone recordings (one
  custody pipeline, enforcement AC on the phone-side receive handler). `Verify:` bifrost
  `CaptureDeliveryTests.swift::testWatchRelayedFileEntersStagingQueue` (new).
- [x] Haptic events fire on start/pause/resume/stop transitions of the watch session model.
  `Verify:` bifrost `Yggdrasil/YggdrasilTests/WatchHapticsTests.swift::testHapticPerTransition`
  (new; haptic player injected).

## How to Verify (Pre-Merge)

- bifrost CI green including the watch build; `swiftlint --strict` clean. Real haptic feel and
  background WC behavior are HCAP-09 walkthrough steps.

## Out of Scope

- Any watchOS networking, streaming, or complication surfaces. Mimer content on the Watch
  (topology: never). Phoneless native delivery (documented floor: stock Voice Memos).
  Watch-side settings/consent UI (phone owns JC).

## Restart / Durability Posture

Queued watch recordings are files on the Watch plus WCSession's own persistent transfer queue —
both survive app termination; the queue view is rebuilt from disk + `WCSession.outstandingFileTransfers`.
User consequence of a watch reboot mid-relay: the transfer resumes or the item reappears queued;
nothing is silently dropped.

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-1/-B3-5)
- `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` (Model 1/Model 3 reasoning, watchOS constraints)

## Related GitHub Issues

Delivered by [`RasmusTho/bifrost` issue #19](https://github.com/RasmusTho/bifrost/issues/19) and
[PR #38](https://github.com/RasmusTho/bifrost/pull/38), linking hub #3026 and this spec file.
