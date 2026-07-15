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

Make CKM measurement reproducible and inspectable while preventing descriptive metrics from becoming rankings, gates, or hidden policy.

## What This Task Does

- Define a versioned metric registry with formulas, detector/configuration inputs, output shape, interpretation, limitations, and machine-readable Goodhart warnings.
- Compute immutable observations through the Q1 query service so each observation binds one complete CKM snapshot and canonical query.
- Persist or serialize the complete semantics-bearing bundle: snapshot/query digests, schema/taxonomy versions, metric definition/version/digest, formula/detector/configuration digests, watermarks, provenance, and generated time.
- Represent vector, composition, citation, confidence, and freshness outputs without a privileged aggregate scalar.

## Concretely

The first registry covers the bounded descriptive measures already named by the audit and inquiry, such as coverage/composition, freshness, confidence, citation completeness, candidate share, assessment distribution, and finding composition. A definition declares `not_for_gating: true` and explicit Goodhart warnings. Identical definition plus snapshot plus query produces the same semantic observation.

## Why This Matters

Unversioned formulas and partially bound observations create false trends. A single score invites ranking and automated authority that CKM is not allowed to hold. Complete binding makes later compatible comparison possible without pretending the observation explains causality.

## Acceptance Criteria

- [ ] Every metric definition has a stable ID, semantic version, canonical definition digest, output/value-state schema, formula/detector/configuration bindings, limitations, and machine-readable `not_for_gating: true` Goodhart warnings.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_definitions_are_versioned_and_warn_against_gating`
- [ ] Metric observations bind the complete snapshot, query, schema, taxonomy, definition, formula, detector, configuration, watermark, provenance, and generated-time bundle.
  Verify: `tests/builderops/ckm/test_metrics.py::test_observation_binds_complete_semantic_bundle`
- [ ] Identical metric definition, canonical query, and snapshot produce byte-identical semantic observation content aside from explicitly excluded volatile fields.
  Verify: `tests/builderops/ckm/test_metrics.py::test_observation_is_deterministic_for_same_snapshot_and_definition`
- [ ] Measured zero, missing, not-applicable, and unsupported remain distinct in metric outputs, and candidate material cannot be silently combined with confirmed material.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_value_states_and_candidate_separation`
- [ ] The public metric surface exposes vectors, distributions, composition, citations, freshness, and confidence but no ranking, gate, prioritization, agent score, or privileged aggregate scalar.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_registry_has_no_scalar_authority_surface`
- [ ] Unknown metric definitions, versions, schema bundles, or unsupported historical modes return typed refusal rather than fallback or coercion.
  Verify: `tests/builderops/ckm/test_metrics.py::test_metric_version_and_semantics_mismatch_refuse`
- [ ] The owner spec records delivered M1 semantics and leaves cadence, window size, minimum snapshot count, M2 history, O2 automation, and federation unresolved.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_metrics.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Inspect serialized observations for full binding and absence of ranking/gating fields.

## Out of Scope

- Comparison or trend claims; O1b owns compatible comparison.
- A fixed observation cadence, time window, or minimum evidence count.
- Rankings, gates, prioritization, agent evaluation, prediction, automation, drift detection, or federation.
- General bitemporal history or retroactive provenance.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Implementation issue #3779 under validation parent #3775, dependency-blocked on #3777. TCD hint: Terra/high; escalate to Sol/high for semantics, compatibility, or authority-boundary uncertainty.
