---
name: Evaluate source note quality
description: Establish evidence-integrity and revisit-value evaluation for YouTube Source Note v2.
task_id: YSNV2-12
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Acceptance and evidence
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-01, YSNV2-02, YSNV2-03, YSNV2-04, YSNV2-05, YSNV2-06, YSNV2-07, YSNV2-08, YSNV2-09, YSNV2-10, YSNV2-11]
depends_on: [RECONCILE_SOURCE_NOTE_V2_CONTRACT.md, FIX_CANDIDATE_TRUTH_SURFACES.md, COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md, PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md, PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md, MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE.md, ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES.md, EXTRACT_GATED_ONTOLOGY_PROPOSALS.md, SELECT_TIMESTAMPED_KEY_MOMENTS.md, APPLY_GOVERNED_INTEREST_OVERLAY.md, CAPTURE_OPT_IN_SOURCE_FRAMES.md]
can_parallelize_with: []
---

# Evaluate Source Note Quality

## Purpose

Make prompt and extraction changes measurable against evidence integrity and revisit value instead of relying on fluent output as a proxy for quality.

## What This Task Does

Defines a versioned gold-set/evaluation harness, mechanical anchor and must-capture metrics, an operator annotation receipt, and the end-to-end invariant matrix. As the final child after YSNV2-01 through YSNV2-11, it owns the parent-closure handoff without making an owner annotation a hidden runtime dependency.

## Concretely

The harness scores evidence integrity, selection, hierarchy, uncertainty, connections, and revisit value. Mechanical gates include anchor validity and must-capture recall. A representative v2 fixture exercises immutable versioned bundle evidence, anchored claims, non-destructive candidate materialization, governed overlay admission, optional-media posture, and no-egress replay together. Frames are assessed only when D1-approved work exists; absence of frames is not a failure for non-visual sources.

## Why This Matters

The most expensive failures are plausible notes that cannot be checked or fail to preserve what mattered. A stable evaluation surface detects regressions before they become a library-wide re-extraction event.

## Acceptance Criteria

- [ ] The evaluation harness rejects a fixture with unanchored or non-entailing rendered claims and records the failed criterion.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_gate_rejects_unanchored_or_non_entailing_claims`.
- [ ] Gold-set metrics record anchor validity and owner must-capture recall with versioned fixture lineage.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_metrics_record_anchor_validity_and_must_capture_recall`.
- [ ] The gold-set annotation scope and any source/media consent are represented by an operator receipt, not inferred from runtime data.
  Verify: operator receipt on the live parent feature Issue validation ledger identified by `docs/YOUTUBE_SOURCE_NOTE_V2/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`.
- [ ] Evaluation and replay never source-egress or mutate human-authored note content.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_evaluation_is_no_egress_and_non_mutating`.
- [ ] The final representative v2 fixture proves the capability-wide invariants and provides the parent-closure handoff after all prerequisite children are delivered.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_source_note_quality.py::test_quality_gate_rejects_unanchored_or_non_entailing_claims tests/knowledge_acquisition/test_source_note_quality.py::test_quality_metrics_record_anchor_validity_and_must_capture_recall tests/knowledge_acquisition/test_source_note_quality.py::test_quality_evaluation_is_no_egress_and_non_mutating tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`
- Record and inspect the operator receipt for gold-set annotation scope and any source/media consent at the parent validation hub.

## Out of Scope

Automated acceptance of subjective quality, background re-extraction, or requiring frames for a source to pass.

## Related Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:med`, `agent:blocked` pending YSNV2-01 through YSNV2-11, including YSNV2-10's external profile contract. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; this final harness and parent-closure gate validates persistence, provenance, replay, media, profile authority, and cross-task convergence.
