---
name: Fix candidate truth surfaces
description: Correct transcript availability, summary confidence, and summary coverage disclosure.
task_id: YSNV2-02
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Reconciliation baseline
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-01]
depends_on: [RECONCILE_SOURCE_NOTE_V2_CONTRACT.md]
can_parallelize_with: []
---

# Fix Candidate Truth Surfaces

## Purpose

Remove the three confirmed V1 candidate-note lies before adding new extraction or storage capability.

## What This Task Does

Makes `transcript_available` evidence-derived, renders the summary confidence that the extractor already validates, and replaces silent leading-500-segment truncation with either full-input processing or an explicit coverage window carried into the extraction result and note.

## Concretely

For a captionless or unusable-transcript record the rendered value is false and no summary implies transcript evidence. Every rendered summary states model confidence and coverage (`segments_seen`, `segments_total`, ratio/window). The implementation must not make a long-source summary look whole-source when it was not.

## Why This Matters

The candidate is human-visible evidence handling. A false availability flag or hidden coverage boundary makes review less safe, not more convenient.

## Acceptance Criteria

- [ ] Candidate `transcript_available` is derived from usable normalized evidence, including an explicit false path.
  Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_transcript_availability_reflects_usable_evidence`.
- [ ] The note renders the schema-validated summary confidence with clear non-authoritative posture.
  Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_rendered_summary_preserves_model_confidence`.
- [ ] Summary extraction either sees all normalized segments or emits a coverage declaration that reaches the rendered note; the former silent first-500 behavior is absent.
  Verify: `tests/knowledge_acquisition/test_summary_extractor.py::test_summary_coverage_is_complete_or_explicitly_declared`.
- [ ] Current-state source documentation describes the corrected surfaces without claiming v2 modules are shipped.
  Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_transcript_availability_reflects_usable_evidence tests/knowledge_acquisition/test_candidate_writeback.py::test_rendered_summary_preserves_model_confidence tests/knowledge_acquisition/test_summary_extractor.py::test_summary_coverage_is_complete_or_explicitly_declared`
- Review `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback` against the corrected implementation and confirm no broader v2 module claim was added.

## Out of Scope

Composable rendering, durable extractions, claims, transcript bundles, and changing title-bearing paths.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: normalized`

## Related GitHub Issues

Draft issue type: `type:bug`, `prio:high`, `agent:blocked` pending YSNV2-01. SBS class: Product/Runtime. Recommended capability: Terra/high; bounded truth-surface fix with focused tests.
