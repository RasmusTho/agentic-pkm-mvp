---
name: Optimize Bounded Query Plans
description: Generalize the Q1 read model with bounded filters, batch plans, indexes, query-plan assertions, and constant query count.
task_id: CKM-MA-Q2
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Implementation tasks
parent_capability: CKM Measurement & Access
prerequisites: [CKM-MA-Q1B]
depends_on: [DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md]
can_parallelize_with: [Define Metric Registry and Observations, Capture Query Questions]
---

# Optimize Bounded Query Plans

## Purpose

Make structured access efficient and reusable at live CKM scale without weakening Q1 snapshot, ordering, cursor, truncation, or refusal guarantees.

## What This Task Does

Add bounded filters and subtree/evidence/assessment/finding/unlinked-artifact read plans, reusable batch loading, supporting indexes, query-plan assertions, and constant query-count targets per page.

## Concretely

Filters are allowlisted and canonicalized. Every query remains hard-limited and keyset-paginated. Batch plans replace per-capability reads; test fixtures assert both result equivalence and bounded SQLite statement counts.

## Why This Matters

The delivered MVP projections repeat per-capability reads and unbounded scans. A performance fix that changes cursor ordering or silently expands bounds would trade correctness for speed.

## Acceptance Criteria

- [ ] Allowlisted capability/subtree/evidence/assessment/finding/unlinked filters remain bounded, canonical, and cursor-compatible.
  Verify: `tests/builderops/ckm/test_query_plans.py::test_bounded_filters_preserve_q1_cursor_contract`
- [ ] Batch plans return the same snapshot-bound DTOs as the Q1 service with constant query count per page.
  Verify: `tests/builderops/ckm/test_query_plans.py::test_batch_read_plan_has_constant_query_count`
- [ ] Required indexes exist and SQLite query plans use indexed predicates for supported live filters.
  Verify: `tests/builderops/ckm/test_query_plans.py::test_supported_filters_use_required_indexes`
- [ ] Projection/overview consumers using the new batch plan do not perform N+1 reads.
  Verify: `tests/builderops/ckm/test_query_plans.py::test_projection_consumers_do_not_regress_to_n_plus_one`
- [ ] Unknown/unbounded filters refuse and Q1 hard limits, ordering, truncation, and snapshot-change behavior remain unchanged.
  Verify: `tests/builderops/ckm/test_query_plans.py::test_query_optimization_cannot_weaken_q1_bounds`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_query_plans.py tests/builderops/ckm/test_query_service.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Live-scale query-plan and statement-count receipt.

## Out of Scope

- Ranking, arbitrary sort, scalar maturity ordering, unbounded export, HTTP/UI, metrics, or observation semantics.
- Weakening cursor or snapshot refusal to improve speed.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md`

## Related GitHub Issues

Implementation issue #3778 under validation parent #3775, dependency-blocked on #3777. May parallelize with #3779/#3780 only with non-overlapping code/test/docs ownership. TCD hint: Terra/high for multi-layer query planning.
