---
name: Normalize And Write Reading Candidates
description: Consume Heimdal-published Karakeep evidence in Mimer/KAP and write deterministic review-required reading candidates.
task_id: KMA-04
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability acceptance criteria"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-03]
depends_on: [FETCH_KARAKEEP_READING_EVIDENCE]
can_parallelize_with: []
---

# Normalize And Write Reading Candidates

## Purpose

Consume Heimdal's durable published-evidence handoff in Mimer/KAP and materialize useful reading
candidates while preserving the governed write choke point.

## What This Task Does

Add a Mimer consumer for the contracted published evidence, resolve/refine meaning without re-fetching
or re-attributing the source, generalize candidate assembly only as required for
`reading_source_note`, and write through `candidate_writeback`/WriteGuard. Advance Mimer's consumer
cursor only across a contiguous durable prefix of materializations; a retryable, blocked, or
item-scoped failure stops that prefix unless a durable failure disposition with replay/audit proof
makes the failed row safely advanceable.

## Concretely

The same published-evidence revision always targets the same candidate path. A candidate contains source link,
Heimdal evidence id/revision, Karakeep provenance, notes/highlights, non-authoritative summary, empty human-
takeaways space, and mandatory draft/review markers.

## Why This Matters

This is the authority-sensitive seam: useful reading material must become visible without allowing
external source data or AI extraction to masquerade as accepted human knowledge.

## SBS Impact

Product/Runtime: Mimer/DRI primary at the Heimdal handoff; HKA, SIP, GOV secondary. Mimer performs no
external egress and no source attribution. Derived assembly plus governed draft-note write.

## Restart / Durability Posture

Assembly is derived from published evidence and replayable without Karakeep egress. Candidate
materialization is deterministic first-write-wins. WriteGuard refusal leaves Mimer's consumer cursor
in place while Heimdal's producer cursor remains independent.

## Acceptance Criteria

- [ ] Published link, note, and highlight evidence maps to deterministic candidate content with intact
  source provenance and no fabricated fields. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_link_note_highlight_mapping_preserves_evidence_and_provenance`.
- [ ] Candidate always carries draft/review-required posture and cannot promote or overwrite an
  existing human artifact. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_is_review_required_and_first_write_wins`.
- [ ] Production call site invokes KAP WriteGuard/candidate writeback and never `/api/capture` or a
  companion adapter. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Consumer performs zero Karakeep egress/re-attribution and advances only its own cursor after
  durable outcome. Verify: `tests/knowledge_acquisition/test_karakeep_handoff_consumer.py::test_consumer_starts_at_handoff_and_owns_only_consumer_cursor`.
- [ ] Blocked/failed writes remain retryable; repeat succeeds once without duplicate note or stage
  receipt. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_blocked_write_retries_idempotently`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_karakeep_candidate_writeback.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_handoff_consumer.py`
- `pytest -q tests/knowledge_acquisition/test_candidate_writeback.py tests/knowledge_acquisition/test_replay.py`
- `ruff check app tests && mypy app`

## Out of Scope

Companion capture, auto-promotion, overwriting reviewed notes, retrieval/index changes, bidirectional
sync, and source deletion propagation.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

Issue #3375 after KMA-03 only. TCD hint: strongest available model / high reasoning; authority-bearing
write-path adjacency, generic candidate refactor, and idempotency require deep review.
