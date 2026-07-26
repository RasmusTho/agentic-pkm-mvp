---
name: Select timestamped key moments
description: Select evidence-linked moments with timestamps independently of frame capture.
task_id: YSNV2-09
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Frames are exceptional
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-05]
depends_on: [PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md]
can_parallelize_with: [EXTRACT_GATED_ONTOLOGY_PROPOSALS]
---

# Select Timestamped Key Moments

## Purpose

Deliver revisit-friendly timestamp selection without coupling its value or correctness to unapproved screenshot work.

## What This Task Does

Generates deterministic moment candidates from transcript/chapter/claim evidence and semantically selects a bounded, diverse set. Each selected moment has a timestamp link, transcript anchors, rationale, and lineage; `frame` is absent until the separate frame task succeeds.

## Concretely

Candidate generation is generous; selection is bounded by source duration, diversity, and support for retained claims or organizing structure. A source with no useful visual content is successful with timestamp-only moments or zero moments.

## Why This Matters

Moment quality can be evaluated separately from media acquisition, and a timestamp is useful even when no legal/retention posture permits a frame.

## Acceptance Criteria

- [ ] Selected moments have stable timestamp links, transcript anchors, content identity, stage/version, and selection rationale.
  Verify: `tests/knowledge_acquisition/test_key_moments.py::test_selected_moments_are_timestamped_anchored_and_lineage_bearing`.
- [ ] Selection honors source-duration budgets, diversity suppression, and claim/structure relevance rather than evenly sampling the timeline.
  Verify: `tests/knowledge_acquisition/test_key_moments.py::test_moment_selection_enforces_budget_diversity_and_evidence_relevance`.
- [ ] Moment capture degrades successfully to timestamp-only output with no frame placeholder or media acquisition.
  Verify: `tests/knowledge_acquisition/test_key_moments.py::test_timestamp_only_moments_need_no_frame_or_media_egress`.
- [ ] System-generated selection rationale follows D6 while quoted/source wording remains in the original language.
  Verify: `tests/knowledge_acquisition/test_key_moments.py::test_moment_rationale_follows_source_language_policy`.

## How to Verify (Pre-Merge)

- Run the four named focused tests across long, short, talking-head, no-visual, and language-policy fixtures.

## Out of Scope

Downloading video, scene/slide analysis, vision captioning, and retained frame bytes.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Frames are exceptional`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:med`, `agent:blocked` pending YSNV2-05. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; selection/provenance state must converge before optional media work.
