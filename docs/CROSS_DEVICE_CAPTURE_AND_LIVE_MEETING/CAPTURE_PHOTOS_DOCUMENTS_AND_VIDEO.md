---
name: Capture Photos Documents And Video
description: iPhone/iPad capture surfaces for photos, receipt/document scans, and video that feed the durable transfer outbox with typed sidecars; the Watch remains audio-relay-only.
task_id: CDLM-04
github_issue: "https://github.com/RasmusTho/bifrost/issues/58"
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-03]
depends_on: [RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md]
can_parallelize_with: [SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD.md, PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md]
---

# Capture Photos Documents And Video

State: Delivered by Bifrost issue #58 / PR #64 on 2026-07-30 (merge commit
`47fea6d5b1a1c1f46f01fd29d592cae312a5ca11`).

## Purpose

Extend capture beyond audio to the remaining owner-priority modalities — photos, receipts,
documents, video — without inventing a second delivery mechanism: every modality is just another
outbox item.

## What This Task Does

- **Photo capture** (camera + photo-library import) on iPhone and iPad, finalized as an outbox
  item with `kind: image`.
- **Receipt/document scan** using the system document scanner (VisionKit document camera):
  multi-page scans finalize as a single PDF outbox item with `kind: document` and a
  `subkind ∈ {receipt, document}` chosen by the user's capture entry point — a UI affordance, not
  an inference.
- **Video capture** (camera, bounded duration per configured cap) finalized as `kind: video`.
- **Typed sidecars.** Each item's envelope carries the CDLM-01 sidecar fields plus per-kind
  minimum metadata (page count for documents; duration and rough byte size for video). No content
  understanding, no OCR, no classification on device (the raw seam, INV-B3-2, extends to all
  modalities: the client ships bytes and capture-time facts, never derived meaning).
- **Finalize-then-enqueue discipline.** A capture becomes an outbox item only as a complete,
  admissible file (temp-name-then-rename within the outbox store), so a crash mid-save leaves a
  recoverable partial *outside* the queue, mirroring INV-B3-1's accountable-place rule.
- **Watch unchanged.** The Watch keeps one-tap audio + relay (HCAP-06). No Watch camera/photo
  surface, no Watch networking (INV-B3-5).

## Concretely

Simulator walk: scan a two-page receipt → one `document/receipt` item appears in the queue
`pending locally` with the original PDF on device; capture a 20-second video with the hub up →
item transfers and shows `backend durably received`; verify by receipt query that the hub holds
one object whose hash matches the local sidecar.

## Why This Matters

The vertical's promise is *capture anything on the device you have in hand*. If modalities fork
delivery paths, every durability proof from CDLM-03 must be re-litigated per kind; by making
modality a sidecar field, one outbox proof covers them all.

## Acceptance Criteria

- [ ] Each modality finalizes into the outbox as a complete admissible file with a correct typed
  sidecar (`kind`, per-kind metadata, `content_sha256` matching the bytes).
  - Verify: bifrost `Yggdrasil/YggdrasilTests/MultiModalCaptureTests.swift::testEachModalityFinalizesTypedOutboxItem`
- [ ] A crash before finalization leaves no queue entry and no orphaned partial inside the outbox
  store; recovery surfaces the partial for retry or discard.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/MultiModalCaptureTests.swift::testUnfinalizedCaptureStaysOutOfQueue`
- [ ] Receipt vs document subkind follows the user's entry point only (no content inference), and
  is carried through envelope and sidecar.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/MultiModalCaptureTests.swift::testSubkindFollowsEntryPointOnly`
- [ ] Oversize video (beyond the configured cap) is refused at capture with a legible state, not
  enqueued-then-rejected.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/MultiModalCaptureTests.swift::testVideoCapRefusedAtCapture`
- [ ] All new items inherit CDLM-03 retention/resend semantics unchanged (spot-checked through the
  shared outbox test seam).
  - Verify: bifrost `Yggdrasil/YggdrasilTests/MultiModalCaptureTests.swift::testNewKindsInheritOutboxSemantics`

## How to Verify (Pre-Merge)

- bifrost CI runs `MultiModalCaptureTests` on both the iPhone and iPad destinations.
- `swiftlint --strict` clean.

## Out of Scope

- Hub-side per-kind processing (OCR, thumbnails, video transcode — later verticals; the hub
  admits and stores under CDLM-01 regardless).
- Live-meeting segment capture (CDLM-09 composes recording with sessions).
- Share-sheet/system-extension ingestion from other apps (future bounded slice).
- Any on-device content analysis (INV-B3-2 extended; INV-CDLM-8).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-2/3/8)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md` (the outbox this feeds)
- `docs/HEIMDAL_CAPTURE_CLIENT/DISCRETE_RECORD_WITH_BACKGROUND_AUDIO.md` (audio precedent this mirrors)

## Related GitHub Issues

One bifrost issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO").
TCD hint: Sonnet / medium — routine AVFoundation/VisionKit + file handling against a
fully-specified outbox seam.
