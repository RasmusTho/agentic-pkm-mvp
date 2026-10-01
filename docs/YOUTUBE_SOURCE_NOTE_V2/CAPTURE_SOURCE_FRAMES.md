---
name: Capture source frames
description: Capture source-dependent frames with bounded temporary media and deletion receipts.
task_id: YSNV2-11
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Frames are exceptional
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-09]
depends_on: [SELECT_TIMESTAMPED_KEY_MOMENTS.md]
can_parallelize_with: []
---

# Capture Source Frames

## Purpose

Retain one bounded contextual frame for each eligible timestamped YouTube acquisition without making frames ordinary rebuildable extractions or retaining downloaded video bytes.

## What This Task Does

Using the revised D1 direction, attempt bounded temporary-media capture for each eligible acquisition, retain one contextual frame when capture succeeds, evaluate visual necessity for additional selected moments, record source-dependent lineage and retention posture, and write a deletion receipt for temporary video bytes.

## Concretely

A capture failure or unavailable video keeps timestamp-only moments. On a successful capture, the retained contextual frame provides visual orientation without needing a visual-necessity result; additional frames must pass visual necessity. Retained frames are `media_derivative` exceptions with explicit usage-rights and sensitivity metadata and `source_dependent` regenerability.

## Why This Matters

Video capture changes rights, egress, retention, and privacy posture. Its failure mode must make the source note less illustrated, never less truthful.

## Acceptance Criteria

- [ ] The production capture call site attempts bounded capture for timestamped moments by default and retains one contextual frame when capture succeeds.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_capture_call_site_retains_context_frame_by_default`.
- [ ] A successful capture retains one contextual frame; failure or unavailable media produces timestamps-only output with no placeholder and does not fail the candidate note.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_context_frame_is_retained_when_capture_succeeds_and_failure_degrades_to_timestamps_only`.
- [ ] After temporary-media cleanup, no video/media bytes remain except retained frames; cleanup emits a deletion receipt.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_temporary_video_deletion_leaves_only_retained_frames_with_receipt`.
- [ ] Retained frames have source-dependent derivative lineage, personal-use rights, internal sensitivity, and perceptual-hash deduplication.
  Verify: `tests/knowledge_acquisition/test_source_frames.py::test_retained_frames_have_exception_metadata_and_phash_deduplication`.

## How to Verify (Pre-Merge)

- Run the four named focused tests and a fixture-level byte inventory after cleanup.

## Out of Scope

Unbounded capture, video retention, frame recapture during text-only replay, and publishing frames.

## Related Docs

- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md :: media_derivative`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Transcript acquisition`

## Related GitHub Issues

Issue #4118 delivers this task as `app/knowledge_acquisition/source_frames.py :: capture_source_frames`, a production stage call site over the #4116 `moment_id`-keyed moments that is not yet wired into acquisition-time note rendering. By default it makes one bounded low-resolution temporary download (size, duration, and frame-count caps), retains one `context_frame` on success plus at most two frames that pass an injected visual-necessity predicate and pHash deduplication, degrades every failure, unavailable source, or replay (egress-blocked) context to timestamps-only output, deletes the temporary directory before any vault write with a `temporary_media_deletion` receipt, and fails visibly when deletion cannot be proven. Retained stills and `frames.json` live under the immutable bundle version folder; a per-attempt ObjectStore record carries the outcome and receipt. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; media, rights, retention, egress, and authority semantics require high capability.
