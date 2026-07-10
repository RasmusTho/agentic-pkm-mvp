---
name: Normalize And Write Reading Candidates
description: Turn stored Karakeep raw evidence into deterministic review-required reading candidates through KAP governed writeback.
task_id: KMA-04
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability acceptance criteria"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-02, KMA-03]
depends_on: [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE, FETCH_KARAKEEP_READING_EVIDENCE]
can_parallelize_with: []
---

# Normalize And Write Reading Candidates

## Purpose

Materialize useful reading candidates while preserving KAP's non-authoritative review posture and
existing governed write choke point.

## What This Task Does

Generalize the YouTube-shaped candidate assembly only as required for `reading_source_note`, map
links/notes/highlights deterministically, retain verbatim source evidence and provenance, run existing
normalization/extraction stages where applicable, and write through `candidate_writeback`/WriteGuard.

## Concretely

The same raw revision always targets the same candidate path. A candidate contains source link,
Karakeep ids/revision, notes/highlights, non-authoritative summary when available, empty human-
takeaways space, and mandatory draft/review markers.

## Why This Matters

This is the authority-sensitive seam: useful reading material must become visible without allowing
external source data or AI extraction to masquerade as accepted human knowledge.

## SBS Impact

Product/Runtime: DRI primary; EBF, HKA, SIP, GOV secondary. Derived assembly plus governed mechanical
draft-note write. No authority promotion or external mutation.

## Restart / Durability Posture

Assembly is derived from raw and replayable. Candidate materialization is deterministic first-write-
wins. WriteGuard refusal or write failure leaves the raw item replayable and emits an item-scoped
failure; it never marks the item terminal.

## Acceptance Criteria

- [ ] Link, note, and highlight raw evidence maps to deterministic candidate content with intact
  source provenance and no fabricated fields. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_link_note_highlight_mapping_preserves_evidence_and_provenance`.
- [ ] Candidate always carries draft/review-required posture and cannot promote or overwrite an
  existing human artifact. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_is_review_required_and_first_write_wins`.
- [ ] Production call site invokes KAP WriteGuard/candidate writeback and never `/api/capture` or a
  companion adapter. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Blocked/failed writes remain retryable; repeat succeeds once without duplicate note or stage
  receipt. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_blocked_write_retries_idempotently`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_karakeep_candidate_writeback.py`
- `pytest -q tests/knowledge_acquisition/test_candidate_writeback.py tests/knowledge_acquisition/test_replay.py`
- `ruff check app tests && mypy app`

## Out of Scope

Companion capture, auto-promotion, overwriting reviewed notes, retrieval/index changes, bidirectional
sync, and source deletion propagation.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

Future child after KMA-02/03. TCD hint: strongest available model / high reasoning; authority-bearing
write-path adjacency, generic candidate refactor, and idempotency require deep review.
