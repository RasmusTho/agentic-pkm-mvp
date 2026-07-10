---
name: Fetch Karakeep Reading Evidence
description: Implement a read-only Karakeep REST source plugin with pagination, revision identity, durable cursor, and item isolation.
task_id: KMA-03
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-01]
depends_on: [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT]
can_parallelize_with: [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE]
---

# Fetch Karakeep Reading Evidence

## Purpose

Acquire saved reading evidence through KAP's source-plugin boundary without writing Karakeep or the
vault and without losing evidence on paging/restart failures.

## What This Task Does

Implement a read-only plugin adjacent to `app/knowledge_acquisition/` that fetches paginated links,
notes, and highlights; normalizes source response errors; persists immutable raw records; records
source revision/provenance; and commits a monotonic cursor only after durable page handling.

## Concretely

One-shot invocation accepts runtime endpoint/credential references, fetches bounded pages, returns
counts and item-scoped errors, and emits no secret-bearing log/event fields.

## Why This Matters

Fetch is the only source-egress boundary. Correct pagination and checkpoint ordering are what make
continuous acquisition complete, replayable, and safe under ordinary network failures.

## SBS Impact

Product/Runtime: EBF primary, DRI secondary. Derived/rebuildable raw writes only; read-only external
API boundary; no HKA write and no companion capture.

## Restart / Durability Posture

Raw records and cursor/checkpoint are durable. Crash before checkpoint replays the page; stable
identity makes repeats no-ops. Crash after checkpoint cannot occur before represented items are
durably accepted or item-scoped dead-lettered.

## Acceptance Criteria

- [ ] Plugin fetches paginated links, notes, and highlights into the contracted raw shape with full
  source provenance. Verify: `tests/knowledge_acquisition/test_karakeep_fetch.py::test_incremental_fetch_persists_all_reading_evidence_and_resumes`.
- [ ] Duplicate revision is a traced no-op; changed content creates revision lineage without
  overwriting raw evidence. Verify: `tests/knowledge_acquisition/test_karakeep_fetch.py::test_duplicate_is_noop_and_changed_revision_preserves_lineage`.
- [ ] Mid-page crash/retry cannot skip or duplicate durable evidence and cursor never regresses.
  Verify: `tests/knowledge_acquisition/test_karakeep_fetch.py::test_page_failure_replays_before_cursor_advance`.
- [ ] Auth/rate-limit/unavailable and malformed-item failures are legible, item/page isolated, and
  secret-safe. Verify: `tests/knowledge_acquisition/test_karakeep_fetch.py::test_failures_are_bounded_and_credentials_are_redacted`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_karakeep_fetch.py` (stubbed HTTP; no network)
- `ruff check app tests && mypy app`

## Out of Scope

Service deployment, source mutation, candidate writeback, schedules, private endpoint/credential
values, browser scraping, and Karakeep MCP.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md`
- `docs/KNOWLEDGE_ACQUISITION/REPLAY_AND_STAGE_EVENTS.md`

## Related GitHub Issues

Future child after KMA-01; parallel with KMA-02. TCD hint: strongest available model / high reasoning;
external API, pagination, secrets, and crash-safe cursor semantics have high defect cost.
