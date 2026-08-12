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

State: Implemented by Issue #4111. The durable runtime contract is current when the governing
implementation PR merges.

## Purpose

Make evidence-bearing derived artifacts durable across process boundaries without confusing them with raw authority or allowing upgraded extraction results to overwrite a candidate note.

## What This Task Does

Persists normalized transcript anchors and structured extractor outputs with `content_identity`, stage/version, model/prompt identity where applicable, and ancestor lineage. Under recorded D5, each upgrade creates a versioned proposal companion rather than overwriting the candidate.

## Concretely

Each segment receives a stable time-derived anchor and an extraction manifest records the exact inputs and version. The note links to artifacts but replay reads raw, never a vault derivative. A profile declares its required and optional extractors before execution; optional failure may materialize a degraded candidate while required failure cannot.

## Why This Matters

Evidence cannot be checked, upgraded, or independently rerun when it exists only in process memory. Persistence without lineage or non-destructive upgrade behavior would be worse than the current limitation.

## Preconditions

- YSNV2-03 is delivered.
- The canonical atomic governed KnowledgePort create-if-absent boundary was delivered by #4132.
  This slice reuses `app.knowledge.write_ops.create_candidate_note_once`; it does not add a second
  HKA creation mechanism or fall back to check-then-write.

## Implemented Artifact Mapping

- `knowledge_acquisition.normalized_transcript` and `knowledge_acquisition.extraction` are
  StorePort-backed `ObjectStore` objects classified as `projection` / `derived` / `reference`.
  Their MetadataBundle contract fields remain top-level; pipeline-specific manifest fields live
  under `extensions`.
- A normalized transcript id is deterministic for
  `(raw_record_id, content_identity, normalize stage version)`. Equal content bytes from distinct
  source items retain distinct normalized, extraction, and restart-cache lineage.
  Each segment carries a stable millisecond time-range anchor plus an ordinal collision breaker.
- Each successful fresh extraction is an immutable run artifact with raw and normalized ancestors,
  exact input anchors, extractor/version, model identity, output, and provenance event ids. The
  process registry cache is only an optimization; same-version acquisition resolves the durable
  artifact after restart.
- Raw evidence, normalized transcripts, and ordinary same-version extraction identities use the StorePort atomic
  create-if-absent seam. Concurrent producers converge on one immutable winner; raw replay rejects
  any non-raw object occupying the requested identity. Explicit replay alone uses a fresh run id.
- A profile classifies every selected extractor before execution as
  `required_for_materialization` or `optional_for_materialization`. Runtime receipts use the short
  `required` / `optional` classification after validation. Required failure blocks a new
  candidate; optional failure may produce a visibly degraded candidate carrying its rerun handle.
  The SourceRegistry validates this exact declaration and discovery carries it unchanged into the
  queue; empty transcripts are classified through the same required/optional failure path.
- Replay always begins at the immutable raw record and forces fresh extraction. Its no-egress
  policy is context-local and checked at every canonical YouTube/ASR source seam, so overlapping
  replays cannot replace global functions or block acquisition in another context. When a candidate
  already exists, the fresh run is written through the canonical create-once boundary as a unique
  versioned `.meta.md` proposal with predecessor, proposal reference, artifact lineage, and write
  receipt. Candidate and human-authored bytes remain untouched.
- Ordinary acquisition also routes a freshly executed extractor-version upgrade against an
  existing candidate to one versioned proposal; a same-version durable/cache hit remains an
  idempotent no-op.

## Acceptance Criteria

- [x] Persisted transcript/extraction artifacts preserve content identity, stage/version, extractor/model lineage, and resolvable segment anchors across restart.
  Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_persisted_extraction_preserves_anchor_and_lineage_across_restart`.
- [x] The required/optional extractor policy materializes a degraded candidate only when all required evidence exists; an optional failure remains visible and rerunnable.
  Verify: `tests/knowledge_acquisition/test_acquire.py::test_optional_extractor_dead_letter_materializes_degraded_candidate_without_erasing_evidence`.
- [x] A required extractor failure blocks a new candidate while preserving successful outputs and its durable dead-letter.
  Verify: `tests/knowledge_acquisition/test_acquire.py::test_required_extractor_dead_letter_blocks_candidate_and_preserves_successes`.
- [x] Re-extraction writes a new versioned proposal companion with predecessor/proposal reference and receipt, and never overwrites the candidate or human-authored content.
  Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_reextraction_writes_versioned_proposal_companion_without_overwriting_candidate`.
- [x] Replay reads raw evidence and does not use a transcript derivative as its source.
  Verify: `tests/knowledge_acquisition/test_replay.py::test_replay_reads_raw_not_transcript_derivative`.

## How to Verify (Pre-Merge)

- Run the five named focused tests.
- Validate an emitted manifest against the resolved metadata-bundle mapping documented by this implementation; do not validate the brief’s example shape.

## Out of Scope

Vault bundle layout, portable transcript projection, and synthesis/claims.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`
- `docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md :: Out of Scope`
- `docs/architecture/metadata-bundle.md :: Required rules`

## Related GitHub Issues

Issue #4111 implements this Product/Runtime slice; #4132 delivered its atomic governed HKA
create-if-absent prerequisite. Persistence, provenance, replay, and non-destructive authority
semantics were verified with the issue-named acceptance tests.
