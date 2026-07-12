---
name: Derive Read-Only Temporal Posture
description: Derive a policy-driven temporal review overlay for a small allowlisted corpus without asserting truth or mutating artifacts.
task_id: TP-01
source_anchor: docs/TEMPORAL_POSTURE/README.md :: First delivery
parent_capability: Temporal Posture
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Derive Read-Only Temporal Posture

## Purpose

Provide an inspectable temporal-review overlay that is honest about what date evidence does and does not establish.

## What This Task Does

Introduce a versioned policy artifact for a small explicit allowlist and a pure derivation adapter. It evaluates only explicit permitted source/artifact dates and exposes `unknown`, `historical`, or `review_due` with the evidence field, calculation time, and policy version. Before-due material receives no `current`, `fresh`, `valid`, or equivalent truth label.

## Concretely

The policy names note kinds, mode (`age_review` or `historical`), permitted timestamp fields in priority order, interval, policy owner, effective date, and rationale. It is advisory configuration outside canonical notes. The adapter is read-only and its output is secondary presentation metadata only.

## Why This Matters

Temporal support reduces cognitive load only if it remains a transparent invitation to review, rather than a silent agent decision about truth or relevance.

## Acceptance Criteria

- [ ] Only explicitly allowlisted kinds receive a temporal overlay; unlisted artifacts remain untouched. Verify: `tests/temporal/test_temporal_posture.py::test_non_allowlisted_kind_has_no_temporal_posture`.
- [ ] Explicit, parseable, policy-permitted dates derive `review_due` exactly at the configured boundary; missing, malformed, timezone-ambiguous, or implausibly future dates derive reasoned `unknown` without fallback. Verify: `tests/temporal/test_temporal_posture.py::test_posture_derivation_uses_only_explicit_date_evidence`.
- [ ] Historical designation is policy-driven and never ages into `review_due`. Verify: `tests/temporal/test_temporal_posture.py::test_historical_never_ages_into_review_due`.
- [ ] Overlay evaluation changes neither canonical artifact bytes nor retrieval result visibility/order. Verify: `tests/temporal/test_temporal_posture.py::test_temporal_posture_is_read_only_and_retrieval_neutral`.
- [ ] Source/index drift and time-based review posture render as independent reasoned signals. Verify: `tests/temporal/test_temporal_posture.py::test_source_drift_and_review_due_are_orthogonal`.
- [ ] Policy failure cannot emit `review_due` or `historical`, and visible wording states that posture is not a truth judgment. Verify: `tests/temporal/test_temporal_posture.py::test_invalid_policy_and_copy_fail_closed`.

## How to Verify (Pre-Merge)

- `pytest -q tests/temporal/test_temporal_posture.py`
- `pytest -q tests/retrieval/test_view_freshness_metadata.py`
- Run the allowlisted-corpus report under a fixed clock and attach the resulting operator receipt to the issue.

## Out of Scope

No revalidation fetch, durable per-claim validity field, automatic expiry, canonical write, timestamp backfill, notification, retrieval ranking/filtering, or use beyond the initial allowlist.

## Related Docs

- `docs/TEMPORAL_POSTURE/README.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`

## Related GitHub Issues

Implementation issue: [#3549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3549). TCD hint: Terra / high reasoning; semantic non-collapse guards and a small, locally testable pure-function core dominate the risk.
