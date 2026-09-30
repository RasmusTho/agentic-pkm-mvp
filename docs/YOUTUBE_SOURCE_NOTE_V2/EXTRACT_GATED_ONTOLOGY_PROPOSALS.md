---
name: Extract gated ontology proposals
description: Produce evidence-anchored ontology proposals only when a deterministic relevance gate passes.
task_id: YSNV2-08
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Claims have evidence
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-05]
depends_on: [PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md]
can_parallelize_with: [SELECT_TIMESTAMPED_KEY_MOMENTS]
---

# Extract Gated Ontology Proposals

## Purpose

Surface potentially useful conceptual structure without laundering it into canonical ontology or filling notes with unsupported modelling prose.

## What This Task Does

Adds a deterministic relevance gate followed by a proposal-only ontology extractor. It emits anchored concepts, relations, distinctions, alternative interpretations, and competency questions only when the source evidences the required signals.

## Concretely

The gate requires two distinct qualifying signal families with repeated anchored evidence. Every emitted element is `proposed`, separates source definition from system paraphrase, and carries confidence plus anchors. A failed gate omits the whole section; it does not emit low-confidence filler.

## Why This Matters

Ontology language has high authority pressure. The gate keeps ordinary concepts useful while refusing to turn every source into a modelling exercise.

## Acceptance Criteria

- [ ] The deterministic gate omits ontology proposals unless the configured distinct, repeated evidence signals are present.
  Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_gate_requires_distinct_repeated_anchored_signals`.
- [ ] Every rendered ontology concept, relation, distinction, and mapping has proposal status, explicit wording class, and evidence anchors.
  Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_output_is_proposal_class_and_fully_anchored`.
- [ ] No ontology output mutates canonical concepts or relations or advances candidate review state.
  Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_extraction_has_no_canonical_write_or_authority_transition`.
- [ ] Ontology `system_paraphrase` follows D6 while source definitions and quotations retain their original language.
  Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_system_paraphrase_follows_source_language_policy`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_gate_requires_distinct_repeated_anchored_signals tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_output_is_proposal_class_and_fully_anchored tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_extraction_has_no_canonical_write_or_authority_transition tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_system_paraphrase_follows_source_language_policy`

## Out of Scope

Promotion into SIP ontology, ontology editing UI, and frame-assisted gate signals.

## Related Docs

- `docs/architecture/metadata-bundle.md :: Required rules`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

[#4115](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4115) — delivered by PR #5741. SBS class: Product/Runtime.

## Delivery record

Delivered implementation:

- `app/knowledge_acquisition/ontology_proposals.py` holds the deterministic, model-free gate. It
  uses closed English/Swedish cue sets for four signal families: definition, taxonomy, relation, and
  distinction. It passes only when at least two families each match in at least two distinct,
  time-bounded transcript segments. The same module re-validates elements at render time.
- `app/knowledge_acquisition/extractors/ontology_extractor.py` registers the `ontology`
  extractor (`extract.ontology`). A failed gate returns an empty, gate-bearing output without a
  model call. The model schema has no status or authority field. Each accepted element is stamped
  `status: proposed`, with `source_definition` and `system_paraphrase` wording classes, bounded
  confidence, and resolvable anchors. A `source_definition` must be a case-preserving verbatim
  span of one anchored transcript segment. Elements that fail anchoring, verbatim-source, or D6 checks are
  dropped and reported.
- `candidate_writeback` renders validated proposals as the `ontology-proposals` module inside
  the non-authoritative proposal band. The section is omitted when the gate fails or when no
  valid element remains. No concept, relation, review-state, or triage-state write occurs.

The extractor is opt-in through explicit extractor selection. It is not part of
`DEFAULT_EXTRACTOR_IDS`, and module routing remains owned by YSNV2-07 (#4114).
