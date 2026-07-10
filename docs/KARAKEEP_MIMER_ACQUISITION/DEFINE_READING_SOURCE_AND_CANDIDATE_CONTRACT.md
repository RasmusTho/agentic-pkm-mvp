---
name: Define Reading Source And Candidate Contract
description: Define Heimdal Karakeep acquisition/published evidence and the Mimer KAP refinement consumer boundary before code.
task_id: KMA-01
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary"
parent_capability: Karakeep Mimer Acquisition
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Reading Source And Candidate Contract

## Purpose

Make Karakeep a conforming **Heimdal** external source and define the published-evidence handoff that
Mimer/KAP consumes, without importing source-specific authority into HKA/GOV.

## What This Task Does

Define Heimdal link/note/highlight evidence, stable source identity/revision, provenance, attribution
and entity-mention fields, tombstone posture, producer cursor, and durable published-event shape.
Define separately how Mimer consumes that event, resolves/refines meaning, advances its own consumer
cursor, and maps it to a draft `reading_source_note` via governed first-write-wins behavior.

## Concretely

Update this specification and the Heimdal/Mimer handoff contract so implementation has named fields,
two explicit cursors, and no ownership decisions remain. No runtime behavior lands in this task.

## Why This Matters

Identity, authority, and cursor mistakes would propagate into every later slice and make apparently
successful ingestion either lossy or falsely authoritative.

## SBS Impact

Product/Runtime boundary work: Heimdal/EBF producer and Mimer/DRI consumer are both named;
HKA/SIP/GOV are secondary. Contract/docs write class; no shipped runtime claim.

## Restart / Durability Posture

The contract fixes durable Heimdal published evidence + producer cursor separately from Mimer's
consumer cursor/candidate. Replay and revisions remain deterministic across restarts without a
distributed transaction.

## Acceptance Criteria

- [ ] Contract assigns Karakeep fetch, identity, revision, provenance, attribution/entity mentions,
  and publication exclusively to Heimdal. Verify: `tests/heimdal/test_karakeep_handoff_contract.py::test_contract_assigns_external_front_to_heimdal`.
- [ ] Handoff fixes the published link/note/highlight shape and separate producer/consumer cursor
  rules; tombstones never delete a Mimer artifact automatically. Verify: `tests/heimdal/test_karakeep_handoff_contract.py::test_published_shape_and_two_cursor_semantics_are_fail_safe`.
- [ ] Candidate mapping mandates `requires_review: true`, `review_state: draft`, deterministic path,
  Karakeep provenance, and KAP WriteGuard materialization from published evidence. Verify: `tests/knowledge_acquisition/test_karakeep_handoff_consumer.py::test_candidate_contract_is_draft_governed_and_deterministic`.
- [ ] Contract explicitly forbids `/api/capture`, companion capture, Karakeep MCP, and embedded
  endpoint/credential values. Verify: doc writeback at
  `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_karakeep_handoff_contract.py tests/knowledge_acquisition/test_karakeep_handoff_consumer.py`
- `python3 scripts/docs_guard.py`

## Out of Scope

Runtime adapter code, service deployment, scheduling, source writes, content promotion, and secret or
endpoint selection.

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

Issue #3372. TCD hint: strongest available model / high reasoning;
authority, cursor, revision, and source-contract errors would cause costly downstream rework.
