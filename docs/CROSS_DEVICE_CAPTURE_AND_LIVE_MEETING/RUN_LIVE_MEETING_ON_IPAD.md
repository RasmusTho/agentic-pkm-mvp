---
name: Run Live Meeting On iPad
description: iPad live meeting surface — segment capture into the outbox, clearly labeled provisional AI blocks beside the user's own notes editor, reconnect resend and reconciled refresh, and the final view separation.
task_id: CDLM-09
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-03, CDLM-06, CDLM-07]
depends_on: [RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md, PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md, ENFORCE_MEETING_BLOCK_OWNERSHIP.md]
can_parallelize_with: [CONSOLIDATE_MEETING_ON_END.md]
---

# Run Live Meeting On iPad

## Purpose

Compose the vertical's flagship flow: sit in a meeting with the iPad, record, watch a provisional
AI understanding grow, and write your own notes beside it — with the boundary between the two
visible, truthful, and mechanically protected.

## What This Task Does

- **Session capture.** Start meeting → opens a CDLM-02 session and records audio in bounded
  segments (fixed target duration, finalized as admissible files) that enter the CDLM-03 outbox
  with `(session_id, session_seq)` sidecar fields, minted monotonically on device. Recording
  continues regardless of connectivity; segments queue like any capture. Pause/resume and
  interruption behavior compose with HCAP-02's recorder discipline.
- **Live surface.** Polls `GET …/projection` and renders two visually distinct regions:
  - **"AI uppdaterar löpande"** — transcript and `derived_projection` blocks (summary, themes,
    provisional decisions, open questions, action candidates) each showing provisionality:
    revision marker, derived-from coverage, and explicit gap markers when the ledger has holes;
  - **"Dina anteckningar"** — the user's notes editor, writing `user_note` blocks through the
    CDLM-07 endpoint with client-minted `(note_block_id, revision)`; notes are retained in the
    client's durable store until the hub's ack persists (same retain-until-receipt discipline as
    media, text-sized). The editor never renders AI content inline in the user region and never
    lets AI blocks displace the user's cursor or content.
- **Template choice.** Session start offers template selection; v1 lists only the generic default,
  wired through the CDLM-06 precedence seam. No participant fields, no invitee inference
  (INV-CDLM-8).
- **Reconnect flow.** On regained connectivity: outbox resends missing segments (CDLM-03), the
  surface refreshes the gap report and projections, and reconciliation renders as new revisions —
  visibly, not as silent content replacement. Unsynced user notes resend idempotently.
- **End meeting.** Stop → closes the session with the declared final count, shows finalization
  state from the CDLM-08 receipt, and renders the final view: consolidated transcript + final
  derived analysis + the user's notes as three distinct artifacts, user notes never interleaved
  into derived output. `needs attention` (missing segments, failed derivations) is prominent
  with the affected identities.

## Concretely

Simulator journey: start meeting → speak (fixture audio) through 3 segments → AI region shows
transcript + analysis revisions growing; type two notes → visible immediately, marked synced on
ack; enable airplane mode through segment 4 → queue shows pending, AI region shows gap marker,
notes still editable; disable → segment 4 uploads, projections reconcile to a new revision, notes
sync; end meeting → final view shows three artifacts, complete.

## Why This Matters

This is the surface where every invariant meets the user. If provisionality is not visible, the
user trusts a draft as truth; if the regions blur, INV-CDLM-6's guarantee exists only server-side
while the screen misleads; if reconnect silently rewrites, the user cannot trust what they saw a
minute ago. The UI here is the product expression of the contract, not decoration.

## Acceptance Criteria

- [ ] Meeting segments are minted with monotonic `session_seq`, finalized as admissible files, and
  enter the outbox with session sidecar fields; recording continues offline.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/LiveMeetingSessionTests.swift::testSegmentsMintMonotonicallyIntoOutbox`
- [ ] The two regions are structurally separate: derived blocks render only in the AI region with
  revision + coverage + gap provisionality markers; the user region renders only `user_note`
  content.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/LiveMeetingSessionTests.swift::testRegionSeparationAndProvisionalityMarkers`
- [ ] User notes persist locally at write time, send through the user-note endpoint with stable
  `(note_block_id, revision)`, survive relaunch unsent, and resend idempotently.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/LiveMeetingSessionTests.swift::testUserNotesRetainedUntilAckAndResendSafely`
- [ ] Reconnect resends exactly the ledger-missing segments and renders reconciliation as a new
  revision without discarding the user's scroll/editor state or any note content.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/LiveMeetingSessionTests.swift::testReconnectResendsMissingAndRendersNewRevision`
- [ ] The final view renders three distinct artifacts with user notes verbatim and separate, and
  surfaces the receipt's needs-attention state prominently when present.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/LiveMeetingSessionTests.swift::testFinalViewSeparatesArtifactsAndSurfacesGaps`
- [ ] The composed journey (record → disconnect → reconnect → end) runs as an XCUITest on the iPad
  destination.
  - Verify: bifrost `Yggdrasil/YggdrasilUITests/LiveMeetingJourneyTests.swift::testMeetingWithReconnectJourney`

## How to Verify (Pre-Merge)

- bifrost CI: `LiveMeetingSessionTests` + the iPad journey.
- `swiftlint --strict` clean; existing B1/B2/B3 journeys stay green on the same head.

## Out of Scope

- Hub-side behavior (CDLM-01/02/06/07/08 own all of it).
- Rich templates, participant/owner fields, diarization display (later work; ADR-0060 gates).
- Photo/document attachment into a live session (captures during a meeting queue as ordinary
  items; visual attachment to the meeting page is a future bounded slice).
- iPhone meeting layout parity (functional via shared view-models; iPad is the target surface).
- Push transport (polling per CDLM-06's v1 posture).

## Restart / Durability Posture

Durable on device: outbox segments (CDLM-03), user notes until acked, session identity, and the
last-fetched projection snapshot as an explicit stale cache. After relaunch mid-meeting the user
resumes the session with all local evidence intact; the AI region renders the stale snapshot
marked as stale until the next poll answers — it may visibly lag, it never invents. What does not
survive: in-flight poll state and editor cursor position. The trust consequence is bounded: a
relaunch can cost you your place on the page, never a note, a segment, or a receipt.

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-4/5/6/8/9)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ENFORCE_MEETING_BLOCK_OWNERSHIP.md` (the seam the editor writes)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (iPad shell conventions; the sibling surface family)
- `docs/HEIMDAL_CAPTURE_CLIENT/DISCRETE_RECORD_WITH_BACKGROUND_AUDIO.md` (recorder discipline composed here)

## Related GitHub Issues

One bifrost issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/RUN_LIVE_MEETING_ON_IPAD").
TCD hint: Opus / high — the composition surface; region separation, reconnect truthfulness, and
retain-until-ack notes are all trust-bearing.
