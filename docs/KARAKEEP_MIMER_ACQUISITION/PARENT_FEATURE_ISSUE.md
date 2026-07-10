State: FILED as GitHub issue #3367 (`agent:blocked` validation hub). This file is the archived local
contract pointer; GitHub owns live backlog and validation state.

# feat: acquire Karakeep reading evidence into governed Mimer candidates

## Context

D1 in `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md` selects self-hosted Karakeep as the
read-later/highlight source. Accepted ADR-0049 requires Heimdal to own every external
watch→fetch→attribute→publish front end and Mimer to begin at refinement. This feature implements B2
across that handoff, not companion capture, while preserving review-required authority.

## Scope

Define the Heimdal published-evidence→Mimer refinement contract; deploy a managed Karakeep service;
fetch, identify, attribute, and publish saved links/notes/highlights in Heimdal; consume the handoff
in Mimer/KAP through `candidate_writeback`; coordinate safe runs; and prove the real flow.

## Source Anchors

- `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 B2 — Karakeep self-host`
- `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary`
- `docs/KNOWLEDGE_ACQUISITION/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md :: Decision §1`

## SBS Impact

- Primary subsystem: Heimdal/EBF → Mimer/DRI runtime boundary
- Secondary subsystem(s): HKA, SIP, GOV, OEF, EXE
- Write class: derived/rebuildable published evidence plus governed mechanical draft-candidate write
- Authority impact: source and AI output remain non-authoritative and review-required
- Persistence impact: durable Heimdal published evidence/source cursor; separate Mimer consumer cursor, candidate note, and receipts
- Derived/rebuildable impact: Mimer refinement remains replayable from published evidence
- Human knowledge impact: creates draft source candidates only; no promotion
- Memory impact: none
- Retrieval/context impact: later indexing may consume accepted candidate artifacts; no ranking change
- Sync/deployment impact: adds a managed mac-mini service and scheduled acquisition worker
- External boundary impact: Karakeep REST reads; endpoint and credential values remain operator-owned
- New or changed contract: Heimdal Karakeep published-evidence → Mimer KAP refinement handoff
- Owner-doc impact: follow-up after acceptance
- Transition debt impact: adds bounded service operations; reduces read-later ingestion gap
- Fitness rule impact: strengthens external-source provenance, idempotency, and secret containment

## Constraints

- KAP `candidate_writeback` is the only candidate materialization path; never `/api/capture` or a
  companion-capture adapter.
- Heimdal alone contacts Karakeep and owns source identity, provenance, attribution/entity mentions,
  producer cursor, and durable publication; Mimer begins only at published evidence.
- Heimdal and Mimer use separate cursors; no direct cross-constituent call or distributed transaction.
- No Karakeep MCP integration is built here.
- No private endpoint or credential value is committed, logged, or specified.
- No auto-promotion, overwrite of existing human artifacts, or cursor advance before durable work.
- Incremental runs are replayable, item-isolated, and idempotent.

## Acceptance Criteria

- [ ] All six child tasks are delivered in order with receipts. Verify: parent issue implementation-task checklist and linked merged PRs.
- [ ] A saved link with note/highlight reaches a deterministic draft KAP candidate with complete
  Karakeep provenance and no capture call. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Restart, duplicate fetch, partial page failure, and overlapping schedule do not skip or
  duplicate evidence across either constituent. Verify: `tests/heimdal/test_karakeep_schedule.py::test_failed_or_overlapping_run_preserves_constituent_cursors`.
- [ ] Real test-channel proof records source item, published-evidence identity, candidate path, both
  cursors, stage receipts,
  replay result, and secret-free logs. Verify: validation receipt on this issue using
  `docs/KARAKEEP_MIMER_ACQUISITION/PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md :: Acceptance Criteria`.
- [ ] Owner docs are promoted only after acceptance. Verify: doc writeback at
  `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: State` plus the governing Heimdal and KAP owner-doc status.

## Implementation Tasks

Specification: `docs/KARAKEEP_MIMER_ACQUISITION/`.

1. #3372 — define Heimdal acquisition/published-evidence → Mimer refinement contract.
2. #3373 — deploy Karakeep as a managed service, parallel with fetch implementation.
3. #3374 — Heimdal fetches, attributes, and publishes Karakeep evidence, parallel with deployment.
4. #3375 — Mimer consumes published evidence and writes reading candidates.
5. #3377 — coordinate incremental producer/consumer acquisition.
6. #3376 — prove and accept Karakeep → Mimer.

Order: `1 → (2 ∥ 3 → 4) → 5 → 6`.

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
- `pytest -q tests/heimdal/test_karakeep_handoff_contract.py`
- `pytest -q tests/heimdal/test_karakeep_ingestion.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_candidate_writeback.py`
- `pytest -q tests/heimdal/test_karakeep_schedule.py`
- `pytest -q tests/ops/test_karakeep_service_contract.py`
- Final test-channel procedure in `PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md`.

## Source Docs

- `docs/KARAKEEP_MIMER_ACQUISITION/README.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/KNOWLEDGE_ACQUISITION/README.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Applies learning (optional)
