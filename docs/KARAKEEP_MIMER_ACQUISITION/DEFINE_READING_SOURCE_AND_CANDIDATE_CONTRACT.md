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

Define how Karakeep link/note/highlight evidence conforms to the existing canonical
`heimdal.observation.published.v1` schema: stable source identity/revision, the schema's complete
identity/time/actor/entity/content/confidence/provenance/sensitivity/consent families, and tombstone
posture. Define separately how the existing `mimer.candidate_projector` consumer and
`app.heimdal.candidate_projection.project_pending_candidates` path are extended to map that event to
a draft `reading_source_note` via governed first-write-wins behavior. Do not create a parallel event
topic, log, read API, projector, or consumer cursor.

## Concretely

Update this specification and the canonical Heimdal/Mimer handoff docs so implementation has named
Karakeep-to-v1 field mappings and an explicit extension design for the shipped Mimer projector. The
source checkpoint remains Heimdal adapter state; the downstream cursor is the existing
`mimer.candidate_projector` cursor accessed only through `app.heimdal.publish`. No runtime behavior
lands in this task.

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
  and publication exclusively to Heimdal, and maps every saved-item field into the mandatory
  identity/time/actor/entity/content/confidence/provenance/sensitivity/consent families of
  `heimdal.observation.published.v1`. Verify: `tests/heimdal/test_karakeep_handoff_contract.py::test_karakeep_mapping_conforms_to_canonical_published_v1_schema`.
- [ ] Handoff reuses the append-only Heimdal observation log and sanctioned
  `app.heimdal.publish.publish_full_observation` / `read_observations_for_consumer` /
  `advance_cursor_for_consumer` APIs; adapter checkpoint and existing `mimer.candidate_projector`
  cursor remain independent, and no parallel topic/log/read path/cursor is introduced. Verify:
  `tests/heimdal/test_karakeep_handoff_contract.py::test_contract_reuses_canonical_log_and_cursor_seam`.
- [ ] The contract chooses extension of the shipped
  `app.heimdal.candidate_projection.project_pending_candidates` path and its existing
  `mimer.candidate_projector` cursor—not a second KAP consumer—and fixes the additive mapping to
  `reading_source_note`, tombstone no-delete behavior, `requires_review: true`,
  `review_state: draft`, deterministic path, Karakeep provenance, and WriteGuard materialization.
  Verify: `tests/knowledge_acquisition/test_karakeep_handoff_consumer.py::test_contract_extends_existing_mimer_projector_without_parallel_consumer`.
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
- `docs/EVENTS.md :: Heimdal observation log (append-only, per-consumer cursor)`
- `docs/EVENTS.md :: Heimdal event contract schemas`
- `schemas/events/heimdal.observation.published.v1.schema.json`
- `app/heimdal/publish.py :: publish_full_observation / read_observations_for_consumer / advance_cursor_for_consumer`
- `app/heimdal/candidate_projection.py :: CANDIDATE_CONSUMER_ID / project_pending_candidates`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

Issue #3372. TCD hint: strongest available model / high reasoning;
authority, cursor, revision, and source-contract errors would cause costly downstream rework.
