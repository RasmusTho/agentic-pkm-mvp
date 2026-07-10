State: FILED as GitHub issue #3367 (`agent:blocked` validation hub). This file is the archived local
contract pointer; GitHub owns live backlog and validation state.

# feat: acquire Karakeep reading evidence into governed Mimer candidates

## Context

D1 in `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md` selects self-hosted Karakeep as the
read-later/highlight source. This feature implements B2 through KAP, not companion capture, while
preserving review-required authority and replayable acquisition.

## Scope

Define the reading-source contract; deploy a managed Karakeep service; fetch saved links, notes, and
highlights incrementally; normalize and write deterministic KAP reading candidates through
`candidate_writeback`; schedule safe runs; and prove the real test-channel flow.

## Source Anchors

- `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 B2 — Karakeep self-host`
- `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary`
- `docs/KNOWLEDGE_ACQUISITION/README.md :: Cross-Task Invariants / Interaction Safety`

## SBS Impact

- Primary subsystem: EBF (Karakeep acquisition-source adapter)
- Secondary subsystem(s): DRI, HKA, SIP, GOV, OEF
- Write class: derived/rebuildable raw artifacts plus governed mechanical draft-candidate write
- Authority impact: source and AI output remain non-authoritative and review-required
- Persistence impact: durable raw records, cursor/checkpoint, candidate note, and receipts
- Derived/rebuildable impact: normalize/extract/candidate assembly remains replayable from raw
- Human knowledge impact: creates draft source candidates only; no promotion
- Memory impact: none
- Retrieval/context impact: later indexing may consume accepted candidate artifacts; no ranking change
- Sync/deployment impact: adds a managed mac-mini service and scheduled acquisition worker
- External boundary impact: Karakeep REST reads; endpoint and credential values remain operator-owned
- New or changed contract: Karakeep reading-source and candidate mapping under KAP
- Owner-doc impact: follow-up after acceptance
- Transition debt impact: adds bounded service operations; reduces read-later ingestion gap
- Fitness rule impact: strengthens external-source provenance, idempotency, and secret containment

## Constraints

- KAP `candidate_writeback` is the only candidate materialization path; never `/api/capture` or a
  companion-capture adapter.
- No Karakeep MCP integration is built here.
- No private endpoint or credential value is committed, logged, or specified.
- No auto-promotion, overwrite of existing human artifacts, or cursor advance before durable work.
- Incremental runs are replayable, item-isolated, and idempotent.

## Acceptance Criteria

- [ ] All six child tasks are delivered in order with receipts. Verify: parent issue implementation-task checklist and linked merged PRs.
- [ ] A saved link with note/highlight reaches a deterministic draft KAP candidate with complete
  Karakeep provenance and no capture call. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Restart, duplicate fetch, partial page failure, and overlapping schedule do not skip or
  duplicate evidence. Verify: `tests/knowledge_acquisition/test_karakeep_schedule.py::test_failed_or_overlapping_run_never_advances_cursor_unsafely`.
- [ ] Real test-channel proof records source item, raw identity, candidate path, stage receipts,
  replay result, and secret-free logs. Verify: validation receipt on this issue using
  `docs/KARAKEEP_MIMER_ACQUISITION/PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md :: Acceptance Criteria`.
- [ ] Owner docs are promoted only after acceptance. Verify: doc writeback at
  `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: State` plus the governing KAP owner-doc status.

## Implementation Tasks

Specification: `docs/KARAKEEP_MIMER_ACQUISITION/`.

1. #3372 — define reading-source and candidate contract.
2. #3373 — deploy Karakeep as a managed service, parallel with fetch implementation.
3. #3374 — fetch Karakeep reading evidence, parallel with deployment.
4. #3375 — normalize and write reading candidates.
5. #3377 — schedule incremental acquisition.
6. #3376 — prove and accept Karakeep → Mimer.

Order: `1 → (2 ∥ 3) → 4 → 5 → 6`.

## Verification Path

Child issues carry exact `Verify:` tests from their spec files. Stubbed REST tests cover CI; service
manifest tests cover health/secret posture; the final child posts the real test-channel ledger here.

## Validation / Acceptance Path

Keep this parent blocked while children deliver. After each merge, post one child receipt. The final
child reconciles every capability AC, executes restart/replay and negative paths, then proposes owner-
doc promotion and parent closure. Missing evidence leaves the parent open.

## Out of Scope

Direction A connectors; Karakeep's MCP server; interactive assistant access; Raindrop ingestion;
private endpoint/credential selection; public ingress; vault auto-promotion; companion capture;
bidirectional sync or mutation of Karakeep; backups beyond the service runbook contract.

## Suggested Validation

- `python3 scripts/docs_guard.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_contract.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_fetch.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_candidate_writeback.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_schedule.py`
- `pytest -q tests/ops/test_karakeep_service_contract.py`
- Final test-channel procedure in `PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md`.

## Source Docs

- `docs/KARAKEEP_MIMER_ACQUISITION/README.md`
- `docs/KNOWLEDGE_ACQUISITION/README.md`
- `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Applies learning (optional)
