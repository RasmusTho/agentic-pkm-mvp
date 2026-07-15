---
name: Define Metric Registry And Observations
description: Deliver versioned descriptive CKM metrics and immutable, fully bound observations without ranking or gate authority.
task_id: CKM-MA-M1
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions
parent_capability: CKM Measurement & Access
prerequisites: [CKM-MA-Q1B]
depends_on: [CKM-MA-Q1B]
can_parallelize_with: [CKM-MA-Q2, CKM-MA-O1A]
---

# Define Metric Registry And Observations

## Purpose

Make CKM measurement reproducible and inspectable while permitting bounded human-advisory use and preventing metrics from becoming rankings, gates, hidden policy, or an expensive KPI system that costs more than it helps.

## What This Task Does

- Define a versioned metric registry with formulas, detector/configuration inputs, output shape, interpretation, intended/prohibited uses, approval owner, limitations, and machine-readable Goodhart warnings.
- Compute immutable observations through the Q1 query service so each observation binds one complete CKM snapshot and canonical query.
- Persist or serialize the complete semantics-bearing bundle: snapshot/query digests, schema/taxonomy versions, metric definition/version/digest, formula/detector/configuration digests, watermarks, provenance, and generated time.
- Represent vector, composition, citation, confidence, and freshness outputs alongside any aggregate maturity value; label the aggregate `human_advisory_only` and never emit it without its evidence-rich components and Goodhart warning.

## Concretely

The first registry contains no more than six bounded descriptive metric families selected from coverage/composition, freshness, confidence, citation completeness, candidate share, evidence-state distribution, and finding composition. A definition declares intended/prohibited uses, its approval owner, `not_for_gating: true`, and explicit Goodhart warnings. Aggregate maturity may be exposed as a small human-advisory input only when the same result includes the underlying vector, evidence, citations, freshness, confidence, composition, limitations, and `human_advisory_only`. Identical definition plus snapshot plus query produces the same semantic observation. TCD is a registry admission rule: a new or deeper metric is rejected when its expected decision benefit does not justify implementation, review, interpretation, and maintenance cost.

## Why This Matters

Unversioned formulas and partially bound observations create false trends. A score shown without its components invites KPI optimization and false confidence; a score that is expensive to explain can also reduce total development efficiency. Complete binding and co-present drill-down make bounded advisory use possible without pretending the observation explains causality or deserves authority.

## Acceptance Criteria

- [x] The owner decision permits aggregate maturity as a small human-advisory input, prohibits sole-input and automated authority use, and applies TCD to metric depth.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted pre-implementation owner decisions`
- [ ] Every metric definition has a stable ID, semantic version, canonical definition digest, purpose, intended/prohibited uses, approval owner, output/value-state schema, eligible population/cohort/denominator rules, formula/detector/configuration bindings, limitations, and machine-readable `not_for_gating: true` Goodhart warnings.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_definitions_are_versioned_and_warn_against_gating`
- [ ] Metric observations bind the complete snapshot, query, schema, taxonomy, definition, formula, detector, configuration, watermark, provenance, and generated-time bundle.
  Verify: `tests/builderops/ckm/test_metrics.py::test_observation_binds_complete_semantic_bundle`
- [ ] Identical metric definition, canonical query, and snapshot produce byte-identical semantic observation content aside from explicitly excluded volatile fields.
  Verify: `tests/builderops/ckm/test_metrics.py::test_observation_is_deterministic_for_same_snapshot_and_definition`
- [ ] Measured zero, missing, unassessed, and unsupported remain distinct in metric outputs, and candidate material cannot be silently combined with confirmed material.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_value_states_and_candidate_separation`
- [ ] The public metric surface exposes vectors, distributions, composition, citations, freshness, confidence, limitations, and Goodhart warnings; any aggregate is `human_advisory_only`, is never emitted alone, and cannot drive machine ranking, gating, prioritization, agent scoring, or action.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_registry_bounds_advisory_aggregate_without_scalar_authority`
- [ ] Every new or materially deepened metric is justified in its Issue/PR by expected decision benefit versus implementation, review, interpretation, and maintenance cost; no runtime TCD registry or enforcement machinery is added.
  Verify: metric Issue/PR scope receipt plus doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted pre-implementation owner decisions`
- [ ] Unknown metric definitions, versions, schema bundles, or unsupported historical modes return typed refusal rather than fallback or coercion.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_version_and_semantics_mismatch_refuse`
- [ ] The owner spec records delivered M1 semantics and leaves cadence, window size, minimum snapshot count, M2 history, O2 automation, and federation unresolved.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_metrics.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Inspect serialized observations for full binding, co-present drill-down, advisory labels, and absence of machine ranking/gating fields.

## Out of Scope

- Comparison or trend claims; O1b owns compatible comparison.
- A fixed observation cadence, time window, or minimum evidence count.
- Machine rankings, gates, automated prioritization, agent evaluation, prediction, automation, drift detection, or federation. Human use of the fully explained aggregate as one small advisory input is in scope.
- General bitemporal history or retroactive provenance.
- Runtime TCD scoring, cost telemetry, or a second governance registry for metric admission.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Implementation issue #3779 under validation parent #3775, dependency-blocked on #3777 and reconciliation of its Issue contract to the accepted metric-use decision. TCD hint: Terra/high; escalate to Sol/high for semantics, compatibility, or authority-boundary uncertainty.
