---
name: Schedule Incremental Karakeep Acquisition
description: Run bounded incremental acquisition with overlap exclusion, health gating, honest receipts, and safe checkpointing.
task_id: KMA-05
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Execution order"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-04]
depends_on: [NORMALIZE_AND_WRITE_READING_CANDIDATES]
can_parallelize_with: []
---

# Schedule Incremental Karakeep Acquisition

## Purpose

Turn the proven one-shot flow into unattended bounded acquisition without concurrent runs, silent
failure, or unsafe cursor advancement.

## What This Task Does

Add the runtime entrypoint and managed schedule, service-health preflight, one-run lease/lock, bounded
page/item limits, timeout/backoff, per-run summary receipt, and failure exit semantics. Scheduling
invokes the same one-shot pipeline; it does not duplicate source or write logic.

## Concretely

Each invocation reports fetched/new/no-op/failed/written/blocked counts, start/end cursor, health, and
trace id. A second overlapping invocation exits as `already_running`; partial failure exits nonzero
and retains a safe checkpoint.

## Why This Matters

Unattended execution multiplies small failure modes. Overlap exclusion and truthful receipts keep a
routine poll from silently skipping evidence or duplicating governed writes.

## SBS Impact

Product/Runtime: OEF/EXE primary; EBF and DRI secondary. Runtime control-loop and observability change;
no authority semantics change.

## Restart / Durability Posture

The lease expires or is safely recoverable after process death. The durable cursor is the restart
point; run receipts are append-only diagnostics. Schedule state cannot substitute for raw evidence or
candidate durability.

## Acceptance Criteria

- [ ] Production scheduled entrypoint health-gates and invokes the one-shot KAP pipeline with bounded
  work. Verify: `tests/knowledge_acquisition/test_karakeep_schedule.py::test_schedule_calls_health_gated_bounded_pipeline`.
- [ ] Overlapping runs cannot execute source or write calls concurrently. Verify:
  `tests/knowledge_acquisition/test_karakeep_schedule.py::test_overlap_returns_already_running_without_side_effects`.
- [ ] Failure/timeout/restart keeps safe cursor state and next run resumes idempotently. Verify:
  `tests/knowledge_acquisition/test_karakeep_schedule.py::test_failed_or_overlapping_run_never_advances_cursor_unsafely`.
- [ ] Run receipt is truthful, item-scoped, traceable, and secret-safe. Verify:
  `tests/knowledge_acquisition/test_karakeep_schedule.py::test_run_receipt_counts_outcomes_and_redacts_configuration`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_karakeep_schedule.py`
- `pytest -q tests/knowledge_acquisition/test_karakeep_fetch.py tests/knowledge_acquisition/test_karakeep_candidate_writeback.py`
- `ruff check app tests && mypy app`

## Out of Scope

Real test-channel acceptance, dynamic scheduler UI, webhook/public ingress, high availability, source
mutation, and credentials/endpoints.

## Related Docs

- `docs/ENVIRONMENTS.md`
- `docs/OBSERVABILITY.md`

## Related GitHub Issues

Future child after KMA-04. TCD hint: standard/strong model, high reasoning; concurrency, restart, and
checkpoint safety dominate the small code surface.
