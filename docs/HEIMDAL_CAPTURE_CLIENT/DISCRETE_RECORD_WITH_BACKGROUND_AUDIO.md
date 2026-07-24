---
name: Discrete Record With Background Audio
description: Press-to-record voice capture that keeps recording in the background, pauses/resumes across interruptions, and finalizes admissible .m4a segments into local staging.
task_id: HCAP-02
source_anchor: docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md :: §3 Posture A
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-01]
depends_on: [HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING]
can_parallelize_with: [DEVICE_REGISTRATION_AND_CONSENT_SURFACE]
---

# Discrete Record With Background Audio

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

State: **Implemented.** Delivered by
[`RasmusTho/bifrost` PR #28](https://github.com/RasmusTho/bifrost/pull/28)
(issue #15, 2026-07-21). Physical-device background and interruption confirmation remains part of
HCAP-09 rather than this implementation receipt.

## Purpose

Posture A's J0: the human presses record, talks (possibly for a long time, screen locked, phone
pocketed), presses stop. The recording must survive backgrounding and interruptions — the study's
known failure cases — and end as a complete, admissible file. This is the capture heart of B3;
it stops at local staging (delivery is HCAP-03).

## What This Task Does

- Wires an `AVAudioSession` (`.record` category) + `AVAudioRecorder` (or `AVAudioEngine` file
  writer — implementer's choice) recorder behind the HCAP-01 state machine. Output: `.m4a`
  (AAC — one of the adapter's admissible extensions), named
  `heimdal-<device_short_id>-<yyyyMMdd-HHmmss>-<seq>.m4a` (informational only — the hub parses
  nothing from filenames; uniqueness is what matters).
- Enables the **audio background mode** in the target's Info settings so recording continues when
  the app leaves the foreground/screen locks (free-provisioning compatible;
  `APP_DEPLOYMENT_POSTURE.md`).
- **Interruption handling:** `AVAudioSession.interruptionNotification` (calls, Siri, other audio)
  → state machine `paused`; auto-resume on `.shouldResume`, otherwise surfaced resume affordance.
  Route changes and session failures finalize the current segment rather than losing it — a
  paused-then-abandoned session still yields a complete file of what was captured (INV-B3-1).
- Finalized segments land in the app's local **staging directory** with their state-machine entry
  (`staged`), visible in the Heimdal area's list with duration + timestamp.
- Mic permission flow with a truthful pre-prompt (why Heimdal records; single-party posture per
  ADR-0049 §3).

## Concretely

Simulator: record 3s → home screen → return: still `recording` → stop → item appears `staged`
with a playable local `.m4a`. Unit level: injected fake recorder drives
interruption → pause → resume → stop and asserts one finalized segment; a session failure mid-way
asserts a finalized partial segment, never a vanished one.

## Why This Matters

If backgrounding or a phone call silently kills a capture, the human loses the thought they
trusted the system with — the exact trust failure Heimdal exists to prevent. Completeness at the
segment level is also what makes downstream delivery discipline (HCAP-03) sufficient for
end-to-end no-loss.

## Acceptance Criteria

- [x] Recording continues across backgrounding (background audio mode active). `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CaptureRecorderTests.swift::testBackgroundTransitionKeepsSessionRecording`
  (new; state-machine + session-config level).
- [ ] Physical-device background/lock-screen and interruption behavior is confirmed by the
  operator walkthrough. `Verify:` HCAP-09 walkthrough receipt; this is device truth, not part of
  the HCAP-02 implementation receipt.
- [x] Interruption pauses; resume resumes; abandonment finalizes a complete segment of captured
  audio. `Verify:` bifrost
  `CaptureRecorderTests.swift::{testInterruptionPausesAndResumes,testAbandonedSessionFinalizesSegment}`
  (new; injected recorder).
- [x] Finalized segments are `.m4a` with unique names in staging and appear in the staged list.
  `Verify:` bifrost `CaptureRecorderTests.swift::testFinalizedSegmentStagedWithUniqueName` (new).
- [x] Stop → finalize never leaves a zero-byte or unclosed file; the file is fully written before
  the state machine reports `staged` (enforcement AC on the production finalize path). `Verify:`
  bifrost `CaptureRecorderTests.swift::testStagedImpliesFullyWrittenFile` (new; asserts through
  the real finalize path with a temp staging dir).

## How to Verify (Pre-Merge)

- bifrost CI green; `swiftlint --strict` clean. True background/lock-screen behavior is
  simulator-limited — the on-device confirmation is an explicit HCAP-09 walkthrough step, not a
  claim this PR makes.

## Out of Scope

- Delivery to the watched folder (HCAP-03). Watch capture (HCAP-06). Any ASR/analysis of the
  audio (INV-B3-2 — never). Location/motion metadata (HCAP-07). Posture B/always-on capture (a
  future grant + adapter change per the consent-ledger design; not built).

## Restart / Durability Posture

A recording in progress when the app is force-killed survives as whatever the recorder had
flushed. On next launch, every orphaned `.m4a` is opened and decoded through AVFoundation before it
can become a recovered `staged` item. Only complete, decodable media enters the delivery-pending
queue. Invalid, truncated, empty, or otherwise unverifiable bytes remain untouched on disk and are
surfaced separately as an explicit filename-bearing recovery failure (INV-B3-1's accountable
custody); they are never represented as complete audio. Both staged items and recovery failures are
rebuilt from the staging directory, never from memory.

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-1/-B3-2)
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §3
- `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` (admissible formats; Model 1)

## Related GitHub Issues

Implemented by [`RasmusTho/bifrost` issue #15](https://github.com/RasmusTho/bifrost/issues/15) and
[PR #28](https://github.com/RasmusTho/bifrost/pull/28). The nonblocking automatic-resume retry
affordance found during final review is tracked separately by
[`RasmusTho/bifrost` issue #34](https://github.com/RasmusTho/bifrost/issues/34).
