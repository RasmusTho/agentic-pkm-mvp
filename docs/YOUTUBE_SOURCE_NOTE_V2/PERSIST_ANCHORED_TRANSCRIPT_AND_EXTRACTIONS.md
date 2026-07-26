---
name: Persist anchored transcript and extractions
description: Durably persist rebuildable transcript/extraction artifacts with evidence anchors and lineage.
task_id: YSNV2-04
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Partial-failure policy introduced by v2
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-03]
depends_on: [COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md]
can_parallelize_with: []
---

# Persist Anchored Transcript and Extractions

## Purpose

Make evidence-bearing derived artifacts durable across process boundaries without confusing them with raw authority or allowing upgraded extraction results to overwrite a candidate note.

## What This Task Does

Persists normalized transcript anchors and structured extractor outputs with `content_identity`, stage/version, model/prompt identity where applicable, and ancestor lineage. Under recorded D5, each upgrade creates a versioned proposal companion rather than overwriting the candidate.

## Concretely

Each segment receives a stable time-derived anchor and an extraction manifest records the exact inputs and version. The note links to artifacts but replay reads raw, never a vault derivative. A profile declares its required and optional extractors before execution; optional failure may materialize a degraded candidate while required failure cannot.

## Why This Matters

Evidence cannot be checked, upgraded, or independently rerun when it exists only in process memory. Persistence without lineage or non-destructive upgrade behavior would be worse than the current limitation.

## Acceptance Criteria

- [ ] Persisted transcript/extraction artifacts preserve content identity, stage/version, extractor/model lineage, and resolvable segment anchors across restart.
  Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_persisted_extraction_preserves_anchor_and_lineage_across_restart`.
- [ ] The required/optional extractor policy materializes a degraded candidate only when all required evidence exists; an optional failure remains visible and rerunnable.
  Verify: `tests/knowledge_acquisition/test_acquire.py::test_optional_extractor_dead_letter_materializes_degraded_candidate_without_erasing_evidence`.
- [ ] A required extractor failure blocks a new candidate while preserving successful outputs and its durable dead-letter.
  Verify: `tests/knowledge_acquisition/test_acquire.py::test_required_extractor_dead_letter_blocks_candidate_and_preserves_successes`.
- [ ] Re-extraction writes a new versioned proposal companion with predecessor/proposal reference and receipt, and never overwrites the candidate or human-authored content.
  Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_reextraction_writes_versioned_proposal_companion_without_overwriting_candidate`.
- [ ] Replay reads raw evidence and does not use a transcript derivative as its source.
  Verify: `tests/knowledge_acquisition/test_replay.py::test_replay_reads_raw_not_transcript_derivative`.

## How to Verify (Pre-Merge)

- Run the five named focused tests.
- Validate an emitted manifest against the resolved metadata-bundle mapping documented by this implementation; do not validate the brief’s example shape.

## Out of Scope

Vault bundle layout, portable transcript projection, and synthesis/claims.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`
- `docs/architecture/metadata-bundle.md :: Required rules`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:high`, `agent:blocked` pending YSNV2-03; D5 is resolved. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; persistence, provenance, replay, and non-destructive authority semantics have high defect cost.
