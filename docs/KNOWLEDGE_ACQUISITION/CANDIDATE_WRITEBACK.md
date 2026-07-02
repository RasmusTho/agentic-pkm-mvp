---
name: Candidate Writeback
description: Assemble the candidate and write the youtube_source_note companion artifact (incl. template posture extension) through governed vault mechanics
task_id: KA-05
source_anchor: docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-04]
depends_on: [EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md]
can_parallelize_with: []
---

# Candidate Writeback

## Purpose

The pipeline's terminal stage: bundle the extraction(s) into a candidate and write the
`youtube_source_note` companion artifact into the vault through the governed write path. The
pipeline ends here; triage is human territory.

## What This Task Does

- Candidate assembly per `REFINEMENT_PIPELINE_CONTRACT.md` §`candidate`.
- Writes the note based on the shipped template with metadata + provenance frontmatter,
  `transcript_available`, the AI summary section marked non-authoritative, extraction results as
  suggestion content — through WriteGuard/governed vault-write mechanics (mechanical durable,
  non-authority-bearing write).
- **Template extension shipped here**: adds the mandated posture markers
  (`authority.requires_review: true` + unreviewed review posture) to the template and the written
  note — see the spec's vocabulary caveat (#2793: posture required, token pending owner-doc
  reconciliation).
- Never advances triage state; never touches any existing artifact's governance-bearing metadata.

## Concretely

```
candidate(raw=…, extractions=[summary@1]) → vault: Sources/<title>.md
frontmatter: artifact_class=youtube_source_note, requires_review=true, provenance{…},
transcript_available=true; body: About / AI summary (non-authoritative) / Human takeaways (empty)
```

## Why This Matters

This is the only place the platform touches human-visible surfaces. A note written without posture
markers masquerades as reviewed knowledge; a write outside WriteGuard bypasses the vault-write
invariant ("WriteGuard gates all vault writes").

## Acceptance Criteria

- [ ] Candidate note written through the governed vault-write path (enforced at the production
      call site — the writeback stage has no direct filesystem write).
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_write_goes_through_writeguard_callsite`
- [ ] Note carries the mandated posture markers, full provenance, and the template shape (incl.
      the extension delivered in this task); template file updated in the same PR.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_note_shape_and_posture_markers` + doc diff on `docs/examples/vault-templates/youtube-source-note.md`
- [ ] No triage advancement and no mutation of any existing artifact.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_no_existing_artifact_mutation`
- [ ] A candidate whose note write is blocked (WriteGuard denial fixture) is **not terminal**: the
      failure is item-scoped, loud, and the candidate remains re-runnable.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_blocked_write_is_loud_and_retryable`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_candidate_writeback.py -q` (temp vault fixture)
- Because this touches the vault-write path (shared/hot-path adjacent): run the full
  `pytest -q -m "not pg"` suite before PR, not targeted tests only.
- `ruff check app tests`

## Out of Scope

Human review UX; promotion; note updates on re-acquisition (first slice: new note per item);
resolution of the #2793 token question.

## Restart / Durability Posture

The note is durable (vault). Candidate assembly state is derived and re-runnable from `raw`; a
crash between candidate assembly and note write loses nothing durable — replay reproduces the
candidate, and the write retries idempotently (same note path, same content identity).

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md` §Writeback
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` §3, §4.3

## Related GitHub Issues

One issue. TCD hint: Sonnet / high (vault-write invariant + partial-failure semantics; full
not-pg suite mandatory).
