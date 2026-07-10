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

## Karakeep source item and revision identity

Heimdal's Karakeep adapter is the only component that reads the Karakeep REST API. It canonicalizes
each saved link, note, or highlight as a source snapshot containing the Karakeep item id, item kind,
source URL when present, title, saved note/highlight text, tags, upstream creation/update times, and
the deleted/archived flags exposed by the API. Mimer does not contact Karakeep and never reconstructs
this source snapshot from a candidate.

Identity is deterministic and revision-aware:

- `source_item_identity = karakeep:<item-id>` is the stable identity of the saved item and becomes
  `episode_id` for every revision of that item.
- `content_identity = sha256:<canonical-source-snapshot>` hashes canonical JSON with sorted keys and
  includes the item id, all evidence-bearing fields, and the deletion flag. Credentials, endpoint
  values, fetch timestamps, and cursor values are excluded.
- `observation_id = karakeep:<item-id>:<content-identity-hex>` identifies one immutable revision.
  Re-fetching identical content therefore republishes the same idempotency input and is a no-op.
- A changed snapshot creates a new `observation_id`, sets `revision_of` to the immediately preceding
  observation for the same `source_item_identity`, and uses the adapter's monotone per-item revision
  ordinal as `sequence`. It never edits the earlier observation.
- A source deletion is another revision with `content: null`, `content_structure.karakeep.tombstone:
  true`, and `supersedes` naming the preceding live revision. It is not a delete instruction.

## Published-v1 field map

Every saved item is assembled through `app.heimdal.publish.assemble_observation_payload` and
published through `publish_full_observation`. The adapter supplies the following map; the publisher
stamps `provenance.content_hash` and validates the result before the append.

| Published-v1 field | Karakeep mapping |
|---|---|
| `observation_id` | Immutable revision id defined above. |
| `episode_id` | Stable `karakeep:<item-id>` source-item identity. |
| `observed_at_start` | Karakeep `createdAt`; if absent, the first observed upstream timestamp, explicitly reported with `clock_basis: inferred`. |
| `attributions` | At least the operator-as-recorder attribution from the source-ingestion grant; source authors are additional subject mentions only when the upstream evidence supports them. |
| `confidence` | Structured `source_integrity`, `attribution`, and `temporal` axes with score, method, and calibration; never a scalar. |
| `provenance` | `sensor: karakeep_rest`, `capture_chain: [karakeep, karakeep_rest, heimdal_karakeep_adapter]`, the source `content_identity`, opaque `raw_ref`, stage versions, and publisher-stamped `content_hash`. |
| `sensitivity` | `private` by default; an explicit source policy may only make it stricter. |
| `consent` | The active operator-owned Karakeep source-ingestion grant (`basis: self_record`, non-empty `grant_ref`); third-party source material is marked, and source text does not invent consent. |

### Optional/nullable published-v1 families

`entity_mentions` is emitted only for Heimdal-attributed mentions supported by the source metadata or
content; otherwise it is absent. `content` is the minimized saved note/highlight/excerpt and may be
null for a link-only item or tombstone. `modality` remains null because published-v1 has no text/web
modality token; adding one requires a separately compatible schema revision. `observed_at_end`,
`captured_at`, `clock_basis`, `content_structure`, `raw_ref`, `withheld`, and `scope_hint` are populated
only when their canonical meanings apply. The adapter must not make an optional family required or
smuggle an endpoint, credential, cursor, or private URL into one.

The following fixture is the executable minimal link/note mapping used by the contract test. It
deliberately omits `entity_mentions` and uses a null modality to prove those families remain optional.

<!-- karakeep-published-v1-example:start -->
```json
{
  "observation_id": "karakeep:item-42:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "episode_id": "karakeep:item-42",
  "sequence": 0,
  "revision_of": null,
  "supersedes": null,
  "observed_at_start": "2026-07-10T08:15:00+02:00",
  "clock_basis": "device_metadata",
  "captured_at": "2026-07-10T08:16:00+02:00",
  "attributions": [
    {
      "mention_id": "operator-recorder",
      "role": "recorder",
      "resolution": "resolved",
      "confidence": 1.0,
      "basis": "capture_context"
    }
  ],
  "modality": null,
  "content": "A saved note about the linked article.",
  "content_structure": {
    "karakeep": {
      "item_kind": "link",
      "source_item_identity": "karakeep:item-42",
      "tombstone": false
    }
  },
  "raw_ref": "raw:karakeep:item-42:aaaaaaaa",
  "confidence": {
    "source_integrity": {
      "score": 1.0,
      "method": "karakeep_api_snapshot",
      "calibration": "by_construction"
    },
    "attribution": {
      "score": 1.0,
      "method": "operator_source_grant",
      "calibration": "by_construction"
    },
    "temporal": {
      "score": 1.0,
      "method": "karakeep_created_at",
      "calibration": "by_construction"
    }
  },
  "provenance": {
    "sensor": "karakeep_rest",
    "capture_chain": ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"],
    "content_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "content_identity": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "stage_versions": {"karakeep_adapter": "contract-v1"},
    "raw_ref": "raw:karakeep:item-42:aaaaaaaa"
  },
  "sensitivity": "private",
  "scope_hint": "operator_reading_inbox",
  "consent": {
    "basis": "self_record",
    "granted_by": "operator",
    "third_party": "marked",
    "grant_ref": "grant:karakeep-source-ingestion"
  }
}
```
<!-- karakeep-published-v1-example:end -->

## Canonical publication and cursor seam

The adapter calls only `publish_full_observation`; it does not create a Karakeep topic or log. Its
source checkpoint advances only after published evidence is durable. That checkpoint records the
upstream page/cursor plus the last durable item revision and is Heimdal-owned.

Mimer reads the same append-only observation log only through
`read_observations_for_consumer` and advances only through
`advance_cursor_for_consumer`. Its one consumer id remains `mimer.candidate_projector`. The
consumer cursor advances only after candidate materialization returns `written` or
`already_exists`; a WriteGuard refusal or item-scoped failure leaves it replayable. Source and
consumer cursors are independent and never participate in one transaction.

## Additive Mimer candidate mapping

KMA-04 extends the shipped `app.heimdal.candidate_projection.project_pending_candidates` branch for
events whose `provenance.sensor` is `karakeep_rest`; it does not add another consumer, projector, or
read API. The existing consumer folds revisions, quarantines observed content, and materializes via
the existing guarded `write_candidate_note`/WriteGuard call site.

The additive projection is a `reading_source_note` with `requires_review: true`,
`review_state: draft`, `source_authoritative: false`, and full Karakeep/Heimdal provenance. Its
deterministic first-write-wins path is
`Sources/Reading/Karakeep/<item-id>-<revision-prefix>.md`. Replay of the same revision returns
`already_exists`; a changed revision creates new lineage at a new deterministic path and never
deletes or overwrites a prior or human-reviewed note. A published source tombstone creates a
review-required tombstone candidate linked to the prior revision; it never deletes or overwrites
the prior candidate.

The boundary forbids `/api/capture`, forbids `companion capture`, and forbids `Karakeep MCP`. It
also forbids embedded endpoint or credential values in code, fixtures, events, notes, or receipts.

## Acceptance Criteria

- [ ] Contract assigns Karakeep fetch, identity, revision, provenance, attribution/entity mentions,
  and publication exclusively to Heimdal. It maps every saved item to the schema-required
  `observation_id`, `episode_id`, `observed_at_start`, `attributions`, `confidence`, `provenance`,
  `sensitivity`, and `consent` fields, while defining `entity_mentions`, `content`, and all other
  optional/nullable fields only when applicable—never by falsely making them required. Verify:
  `tests/heimdal/test_karakeep_handoff_contract.py::test_karakeep_mapping_conforms_to_canonical_published_v1_schema`.
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
