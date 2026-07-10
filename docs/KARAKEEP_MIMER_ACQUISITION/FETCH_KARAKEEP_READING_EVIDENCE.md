---
name: Fetch Karakeep Reading Evidence
description: Implement Heimdal's read-only Karakeep REST adapter, identity/provenance/attribution, durable producer cursor, and published handoff.
task_id: KMA-03
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-01]
depends_on: [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT]
can_parallelize_with: [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE]
---

# Fetch Karakeep Reading Evidence

## Purpose

Acquire saved reading evidence through Heimdal's ingestion-organ boundary, attribute what was
observed, and publish the durable handoff Mimer consumes.

## What This Task Does

Implement a read-only adapter under `app/heimdal/` that fetches paginated links, notes, and
highlights; assigns stable identity/revision; stamps provenance, confidence, attribution and entity
mentions; publishes the contracted evidence; and commits Heimdal's monotonic producer cursor only
after publication is durable. It never imports or invokes `app.knowledge_acquisition`.

## Concretely

One-shot invocation accepts runtime endpoint/credential references, fetches bounded pages, returns
counts, published evidence references, and item-scoped errors, and emits no secret-bearing fields.

## Why This Matters

Fetch is the only source-egress boundary. Correct pagination and checkpoint ordering are what make
continuous acquisition complete, replayable, and safe under ordinary network failures.

## SBS Impact

Product/Runtime: Heimdal/EBF primary with EXE/DRI handoff support. Read-only external API boundary;
published evidence is non-HKA. Mimer/KAP and companion capture are not called.

## Restart / Durability Posture

Published evidence and Heimdal's producer cursor are durable. Crash before checkpoint replays the
page; stable identity makes repeated publication a no-op. Producer cursor advancement does not wait
for Mimer refinement once the handoff is durable.

## Acceptance Criteria

- [ ] Heimdal fetches paginated links, notes, and highlights and publishes contracted evidence with
  identity, revision, provenance, confidence, attribution, and entity mentions. Verify: `tests/heimdal/test_karakeep_ingestion.py::test_incremental_fetch_attributes_and_publishes_reading_evidence`.
- [ ] Duplicate revision is a traced no-op; changed content creates revision lineage without
  overwriting published evidence. Verify: `tests/heimdal/test_karakeep_ingestion.py::test_duplicate_is_noop_and_changed_revision_preserves_lineage`.
- [ ] Mid-page crash/retry cannot skip or duplicate durable evidence and cursor never regresses.
  Verify: `tests/heimdal/test_karakeep_ingestion.py::test_page_failure_replays_before_producer_cursor_advance`.
- [ ] Auth/rate-limit/unavailable and malformed-item failures are legible, item/page isolated, and
  secret-safe. Verify: `tests/heimdal/test_karakeep_ingestion.py::test_failures_are_bounded_and_credentials_are_redacted`.
- [ ] Production adapter publishes the handoff without importing/calling Mimer KAP or capture.
  Verify: `tests/heimdal/test_karakeep_ingestion.py::test_adapter_stops_at_published_handoff`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_karakeep_ingestion.py` (stubbed HTTP; no network)
- `ruff check app tests && mypy app`

## Out of Scope

Service deployment, source mutation, candidate writeback, schedules, private endpoint/credential
values, browser scraping, and Karakeep MCP.

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`

## Related GitHub Issues

Issue #3374 after KMA-01; parallel with KMA-02. TCD hint: strongest available model / high reasoning;
external API, pagination, secrets, and crash-safe cursor semantics have high defect cost.
