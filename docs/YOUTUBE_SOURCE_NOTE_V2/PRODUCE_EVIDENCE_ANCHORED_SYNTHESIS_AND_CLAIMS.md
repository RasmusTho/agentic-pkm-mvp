---
name: Produce evidence-anchored synthesis and claims
description: Generate source-bound synthesis and claims that cannot render without evidence anchors.
task_id: YSNV2-05
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-04]
depends_on: [PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md]
can_parallelize_with: []
---

# Produce Evidence-Anchored Synthesis and Claims

## Purpose

Replace an unstructured summary with evidence-anchored proposal artifacts whose coverage, wording, uncertainty, and language posture are inspectable.

## What This Task Does

Adds structured synthesis and claim extractors; separates source wording from system paraphrase; requires anchors for every rendered assertion; and records coverage and confidence caps. Under D6, system-generated prose is English unless the source's original language is Swedish.

## Concretely

An anchorless claim is dropped and reported. A synthesis sentence carries supporting spans or moves to an explicit unsupported/evaluation result. Caption quality and transcript coverage constrain confidence. Direct quotes and `source_wording` preserve the original source language; a translation is never rendered as a quote.

## Why This Matters

The point of a source note is reviewable compression, not fluent prose that looks like it saw evidence it did not see.

## Acceptance Criteria

- [ ] Every rendered claim and synthesis sentence has one or more resolvable evidence anchors; anchorless output is not rendered as a claim.
  Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_renderer_drops_anchorless_claims_and_synthesis_sentences`.
- [ ] Claim output preserves distinct `source_wording` and `system_paraphrase` fields and displays them without conflation.
  Verify: `tests/knowledge_acquisition/test_claims_extractor.py::test_claim_wording_and_paraphrase_are_structurally_distinct`.
- [ ] Coverage, model confidence, and evidence-derived confidence are visible; low-quality captions cap confidence according to the contract.
  Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_reports_coverage_and_caption_quality_confidence_cap`.
- [ ] System prose and `system_paraphrase` are English unless the source's original language is Swedish, while `source_wording` and quotations preserve original source language.
  Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_language_policy_uses_english_unless_source_is_swedish_and_preserves_quotes`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_evidence_synthesis.py::test_renderer_drops_anchorless_claims_and_synthesis_sentences tests/knowledge_acquisition/test_claims_extractor.py::test_claim_wording_and_paraphrase_are_structurally_distinct tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_reports_coverage_and_caption_quality_confidence_cap tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_language_policy_uses_english_unless_source_is_swedish_and_preserves_quotes`

## Out of Scope

Content-profile modules, ontology proposals, moments, overlay reads, and translation presented as source wording or quotation.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Extraction registry`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Partial-failure policy introduced by v2`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:high`, `agent:blocked` pending YSNV2-04; D6 is resolved. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; evidence/provenance and language semantics require high-confidence contract work.
