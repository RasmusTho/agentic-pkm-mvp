---
name: Compare Compatible Observations
description: Compare immutable CKM metric observations only when every semantics-bearing binding is compatible.
task_id: CKM-MA-O1B
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Cross-task invariants / interaction safety
parent_capability: CKM Measurement & Access
prerequisites: [CKM-MA-M1]
depends_on: [CKM-MA-M1]
can_parallelize_with: [CKM-MA-Q2, CKM-MA-O1A]
---

# Compare Compatible Observations

## Purpose

Provide honest snapshot-to-snapshot descriptive comparison without manufacturing a trend, coercing incompatible definitions, or elevating CKM measurements into authority.

## What This Task Does

- Define a compatibility predicate over every semantics-bearing observation field.
- Load two or more M1-retained observations and their immutable source samples, then compare only after replay availability and compatibility succeed.
- Return component-wise deltas, unchanged components, tagged missing states, citations/provenance, and explicit limitations.
- Refuse mismatched metric definitions, formulas, detector/configuration bundles, schemas, taxonomy, query semantics, candidate policy, identity policy, access/redaction policy, value-state semantics, or unsupported history modes.

## Concretely

A comparison is a deterministic derived result over M1-retained immutable observations and source samples. It first proves that every source payload is still replayable under the bound retention policy, then names all input observation IDs/digests and the compatibility decision. Two snapshots are the mathematical minimum for a delta, not evidence of a trend or a justified cadence.

## Why This Matters

Silent comparison across changed definitions or datasets produces persuasive but false movement. Explicit compatibility and refusal keep comparison useful for inspection without allowing it to become a machine gate, ranking, forecast, or causal claim. A human may consider a fully explained aggregate delta as one small advisory input under the accepted metric-use policy.

## Acceptance Criteria

- [ ] Compatibility checks bind metric ID/version/digest, formula/detector/configuration bundles, resource/envelope schemas, taxonomy digest, canonical query semantics, value-state schema, candidate/confirmed policy, identity-policy version, and access/redaction-policy version.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_compatibility_binds_every_semantics_bearing_field`
- [ ] Compatible immutable observations produce deterministic component-wise deltas with input IDs/digests, provenance, freshness, citations, tagged value states, and explicit limitations.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_compatible_observations_produce_deterministic_bound_delta`
- [ ] Any semantics-bearing mismatch returns a typed incompatibility/refusal listing the mismatched fields; no fallback, coercion, or partial comparison occurs.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_semantic_mismatch_refuses_without_partial_comparison`
- [ ] Comparison refuses when any M1-retained source sample has expired, been pruned/deleted, lacks its policy version, or cannot reproduce its bound snapshot digest.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_unavailable_or_tampered_retained_source_refuses_comparison`
- [ ] Measured zero, missing, unassessed, and unsupported transitions remain explicit and cannot be converted into numeric deltas accidentally.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_value_state_transitions_are_not_coerced_to_numbers`
- [ ] Comparison exposes no machine ranking, gate, prioritization, agent score, forecast, causal claim, or automated action. Any aggregate delta is `human_advisory_only`, appears with component-wise deltas and limitations, and is never privileged or sufficient by itself.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_comparison_bounds_advisory_aggregate_without_authority`
- [ ] The API/CLI result states that two snapshots prove only a bounded delta, and cadence/window/minimum evidence count remain hypotheses.
  Verify: `tests/builderops/ckm/test_metric_comparison.py::test_comparison_disclaims_trend_and_cadence_claims`
- [ ] The owner spec records delivered comparison semantics and only the observation evidence actually gathered during the slice.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Observation-gated future work`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_metric_comparison.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Exercise at least one compatible and one mismatch case through the public adapter.

## Out of Scope

- Trend, regression, causality, prediction, drift alerts, gates, rankings, or automated action.
- A fixed cadence, window, or minimum evidence count.
- General bitemporal queries, retroactive history, dashboards, federation, or Product/Runtime authority.
- Comparison whose source snapshots were pruned, expired, deleted, or otherwise cannot be replayed under the accepted 365-day retention policy.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Implementation issue #3781 under validation parent #3775, dependency-blocked on #3779 and reconciliation of its Issue contract to the accepted identity/access/retention decisions. TCD hint: Terra/high; escalate for definition-compatibility or authority-boundary uncertainty.
