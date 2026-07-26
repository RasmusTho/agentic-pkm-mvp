---
name: Capture opt-in source frames
description: Capture approved source-dependent frames with bounded temporary media and deletion receipts.
task_id: YSNV2-11
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Frames are exceptional
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-09]
depends_on: [SELECT_TIMESTAMPED_KEY_MOMENTS.md]
can_parallelize_with: []
---

# Capture Opt-In Source Frames

## Purpose

Optionally retain visually necessary source frames without making frames ordinary rebuildable extractions or retaining downloaded video bytes.

## What This Task Does

Using resolved D1, acquires bounded temporary media, retains one contextual frame from every successful capture, evaluates visual necessity for any additional selected moments, records source-dependent lineage/retention posture, and writes a deletion receipt for all temporary video bytes.

## Concretely

A capture failure or unavailable video keeps timestamp-only moments. On a successful capture, the first retained contextual frame is deliberate visual orientation rather than a visual-necessity result; additional frames must pass visual necessity. Retained frames are `media_derivative` exceptions with explicit usage rights/sensitivity and `source_dependent` regenerability.

## Why This Matters

Video capture changes rights, egress, retention, and privacy posture. Its failure mode must make the source note less illustrated, never less truthful.

## Acceptance Criteria

- [ ] The production capture call site requires the recorded opt-in D1 posture and retains one contextual frame from each successful acquisition.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_capture_call_site_requires_explicit_opt_in_and_retains_context_frame`.
- [ ] A successful capture retains one contextual frame; failure or unavailable media produces timestamps-only output with no placeholder and does not fail the candidate note.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_context_frame_is_retained_when_capture_succeeds_and_failure_degrades_to_timestamps_only`.
- [ ] After temporary-media cleanup, no video/media bytes remain except approved retained frames; cleanup emits a deletion receipt.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_temporary_video_deletion_leaves_only_approved_frames_with_receipt`.
- [ ] Retained frames have source-dependent derivative lineage, personal-use rights, internal sensitivity, and perceptual-hash deduplication.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_retained_frames_have_exception_metadata_and_phash_deduplication`.

## How to Verify (Pre-Merge)

- Run the four named focused tests and a fixture-level byte inventory after cleanup.

## Out of Scope

Always-on capture, video retention, frame recapture during text-only replay, and publishing frames.

## Related Docs

- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md :: media_derivative`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Transcript acquisition`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:low`, `agent:blocked` pending YSNV2-09; D1 is resolved. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; media, rights, retention, egress, and authority semantics require high capability.
