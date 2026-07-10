---
name: Schedule Incremental Karakeep Acquisition
description: Coordinate bounded Heimdal producer and Mimer consumer schedules with separate leases, cursors, and honest receipts.
task_id: KMA-05
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Execution order"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-02, KMA-04]
depends_on: [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE, NORMALIZE_AND_WRITE_READING_CANDIDATES]
can_parallelize_with: []
---

# Schedule Incremental Karakeep Acquisition

## Purpose

Turn the two proven one-shot halves into unattended bounded acquisition without merging Heimdal and
Mimer ownership, overlapping a constituent's own runs, or coupling their cursors.

## What This Task Does

Add coordinated scheduling for the Heimdal producer and Mimer consumer. Each has its own entrypoint,
lease, cursor, bounded work, timeout/backoff and receipt. Karakeep health gates only Heimdal fetch;
Mimer may drain published evidence while Karakeep is down. Coordination occurs through the durable
handoff, never an in-process cross-constituent call or shared transaction.

## Concretely

The combined operator receipt reports Heimdal fetched/published outcomes and producer cursor
separately from Mimer consumed/written/blocked outcomes and consumer cursor. Either half may fail or
lag without falsifying the other half's durable success.

## Why This Matters

Unattended execution multiplies small failure modes. Overlap exclusion and truthful receipts keep a
routine poll from silently skipping evidence or duplicating governed writes.

## SBS Impact

Product/Runtime boundary work: OEF/EXE coordination around Heimdal/EBF producer and Mimer/DRI
consumer. Runtime control-loop and observability change; constituent ownership is preserved.

## Restart / Durability Posture

Each lease expires or is recoverable independently. Heimdal's producer cursor restarts from durable
publication; Mimer's consumer cursor restarts from durable candidate outcome. Schedule state cannot
substitute for either constituent's durable state.

## Acceptance Criteria

- [ ] Scheduler health-gates only Heimdal fetch and lets Mimer consume durable handoff while source is
  unavailable. Verify: `tests/heimdal/test_karakeep_schedule.py::test_source_health_gates_producer_not_consumer`.
- [ ] Per-constituent leases prevent same-side overlap without creating a shared execution lock.
  Verify: `tests/heimdal/test_karakeep_schedule.py::test_constituent_leases_are_independent`.
- [ ] Failure/timeout/restart preserves both independent cursors and resumes idempotently. Verify:
  `tests/heimdal/test_karakeep_schedule.py::test_failed_or_overlapping_run_preserves_constituent_cursors`.
- [ ] Receipt distinguishes published from consumed/written/blocked outcomes and is secret-safe.
  Verify: `tests/heimdal/test_karakeep_schedule.py::test_boundary_receipt_reports_each_constituent_truthfully`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_karakeep_schedule.py`
- `pytest -q tests/heimdal/test_karakeep_ingestion.py tests/knowledge_acquisition/test_karakeep_handoff_consumer.py`
- `ruff check app tests && mypy app`

## Out of Scope

Real test-channel acceptance, dynamic scheduler UI, webhook/public ingress, high availability, source
mutation, and credentials/endpoints.

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/ENVIRONMENTS.md`
- `docs/OBSERVABILITY.md`

## Related GitHub Issues

Issue #3377 after KMA-02 and KMA-04. TCD hint: standard/strong model, high reasoning; concurrency, restart, and
checkpoint safety dominate the small code surface.
