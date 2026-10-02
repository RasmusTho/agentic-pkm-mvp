---
name: Evaluate source note quality
description: Establish evidence-integrity and revisit-value evaluation for YouTube Source Note v2.
task_id: YSNV2-12
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Acceptance and evidence
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-01, YSNV2-02, YSNV2-03, YSNV2-04, YSNV2-05, YSNV2-06, YSNV2-07, YSNV2-08, YSNV2-09, YSNV2-10, YSNV2-11]
depends_on: [RECONCILE_SOURCE_NOTE_V2_CONTRACT.md, FIX_CANDIDATE_TRUTH_SURFACES.md, COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md, PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md, PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md, MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE.md, ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES.md, EXTRACT_GATED_ONTOLOGY_PROPOSALS.md, SELECT_TIMESTAMPED_KEY_MOMENTS.md, APPLY_GOVERNED_INTEREST_OVERLAY.md, CAPTURE_SOURCE_FRAMES.md]
can_parallelize_with: []
---

# Evaluate Source Note Quality

## Purpose

Make prompt and extraction changes measurable against evidence integrity and revisit value instead of relying on fluent output as a proxy for quality.

## What This Task Does

Defines a versioned gold-set/evaluation harness, mechanical anchor and must-capture metrics, an operator annotation receipt, and the end-to-end invariant matrix. As the final child after YSNV2-01 through YSNV2-11, it owns the parent-closure handoff without making an owner annotation a hidden runtime dependency.

## Concretely

The harness scores evidence integrity, selection, hierarchy, uncertainty, connections, and revisit value. Mechanical gates include anchor validity and must-capture recall. A representative v2 fixture exercises immutable versioned bundle evidence, anchored claims, non-destructive candidate materialization, governed overlay admission, bounded frame capture and timestamp-only degradation, and no-egress replay together. Frames are assessed when capture succeeds; unavailable media degrades to timestamps-only.

## Why This Matters

The most expensive failures are plausible notes that cannot be checked or fail to preserve what mattered. A stable evaluation surface detects regressions before they become a library-wide re-extraction event.

## Acceptance Criteria

- [ ] The evaluation harness rejects a fixture with unanchored or non-entailing rendered claims and records the failed criterion.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_gate_rejects_unanchored_or_non_entailing_claims`.
- [ ] Gold-set metrics record anchor validity and owner must-capture recall with versioned fixture lineage.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_metrics_record_anchor_validity_and_must_capture_recall`.
- [ ] The gold-set annotation scope is represented by an operator receipt, not inferred from runtime data.
  Verify: operator receipt on the live parent feature Issue validation ledger identified by `docs/YOUTUBE_SOURCE_NOTE_V2/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`.
- [ ] Evaluation and replay never source-egress or mutate human-authored note content.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_evaluation_is_no_egress_and_non_mutating`.
- [ ] The final representative v2 fixture proves the capability-wide invariants and provides the parent-closure handoff after all prerequisite children are delivered.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_source_note_quality.py::test_quality_gate_rejects_unanchored_or_non_entailing_claims tests/knowledge_acquisition/test_source_note_quality.py::test_quality_metrics_record_anchor_validity_and_must_capture_recall tests/knowledge_acquisition/test_source_note_quality.py::test_quality_evaluation_is_no_egress_and_non_mutating tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`
- Record and inspect the operator receipt for gold-set annotation scope at the parent validation hub.

## Out of Scope

Automated acceptance of subjective quality, background re-extraction, or requiring frames for a source to pass.

## Related Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`

## Related GitHub Issues

Issue #4119 delivers this task as `app/knowledge_acquisition/source_note_quality.py`. `evaluate_source_note` parses a rendered candidate note or D5 proposal companion, resolves every rendered synthesis sentence, source-bound claim, content-module excerpt, timestamped moment and interest-overlay `source_says` quote against the note's own durable lineage (frontmatter-named raw record, normalized transcript, synthesis extraction and key-moments artifacts), and returns a `ysnv2_source_note_quality_report.v1` that names each failed mechanical criterion: `evidence_lineage`, `anchor_validity`, `claim_entailment` (verbatim claim, module-excerpt and overlay wording contained in the cited segments; unrecognized evidence bullets also fail), and `must_capture_recall` (annotated time spans overlapped by a valid rendered anchor, against the gold set's declared threshold). Reports record the subject's artifact lineage and note digest, the gold set's schema, id, version, digest and provenance kind, and routing/moment-budget diagnostics. Selection, hierarchy, uncertainty, connections and revisit value are listed as operator-scored dimensions and are never scored automatically. Evaluation performs no network, model, vault or ObjectStore write.

Gold sets are versioned `ysnv2_source_note_gold_set.v1` documents. Owner annotations must bind operator receipt `ysnv2_gold_set_annotation_scope.v1` (recorded on #4107; 3 videos, about 5–10 must-capture points each), stay within its 3-video scope, and live in the data slot `data/golden/youtube_source_note_v2/owner_gold_set.v1.json`. That slot is empty until the owner supplies real annotations; synthetic fixtures cannot claim the owner receipt or occupy the slot, and no annotation is inferred from runtime data. The four `Verify:` tests use clearly labeled synthetic fixtures only. `test_v2_end_to_end_invariant_matrix` runs the real acquisition-time pipeline with an injected fake media capture and a governed ProfileAgent profile fixture. It proves the following together: immutable versioned bundle evidence, anchored and entailed claims, non-destructive D5 materialization, governed overlay admission with the no-profile path, bounded frame capture with timestamps-only degradation, and no-egress replay. This is the parent-closure handoff evidence. Parent acceptance, the owner's gold-set run, and current-state owner-doc promotion stay with the #4107 coordinator. SBS class: Product/Runtime. Recommended capability: Sol/xhigh.
