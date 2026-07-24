---
name: Surface Interpretation Hazards Honestly
description: Render deterministic descriptive caveats for stale, sparse, candidate-heavy, shared, or snapshot-wide-zero evidence without diagnosing causes.
task_id: CKM-DB-02
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-DB-01]
depends_on: [ESTABLISH_TRUST_AND_PORTFOLIO_FRAMING.md]
can_parallelize_with: []
---

# Surface Interpretation Hazards Honestly

## Purpose

Help the owner see what not to take at face value while keeping CKM interpretation descriptive,
cited, and visibly unable to determine cause.

## What This Task Does

- Add a fixed interpretation-hazard block derived from the same captured projection batch.
- Detect and order only explicit observable states: stale assessments, unavailable/unassessed
  dimensions, candidate-heavy assessed dimensions, shared-evidence indicators delivered by
  Evidence Profile, and dimensions that are 0.00 across every assessed capability.
- Render exact counts, affected capability public IDs, dimension names, and source markers where
  available.
- Use the fixed snapshot-wide-zero caveat from the capability README and never label it a scorer
  defect, missing functionality, regression, or priority.
- Mark renderer-authored interpretation regions so rhetoric tests can inspect generated copy without
  treating citations, capability definitions, finding statements, or the required non-trend
  disclaimer as renderer claims.

## Concretely

For a dimension measured as zero for every assessed capability, render:

```text
Snapshot-wide zero: <dimension> is 0.00 for every assessed capability in this snapshot.
CKM cannot determine whether that reflects missing evidence, current metric coverage, or
portfolio state.
```

For no observed hazards, render `No listed interpretation hazards for this captured projection.`
This is not a claim that the CKM is complete or correct.

## Why This Matters

The current projection can look precise while its substrate is sparse, shared, stale, or
unassessed. Replacing that risk with an unsourced “blind spot” diagnosis would be equally
misleading. A bounded descriptive vocabulary makes uncertainty legible without granting the
renderer causal or backlog authority.

## Acceptance Criteria

- [ ] Hazard rows derive only from the already-captured cockpit projection batch and use deterministic type/dimension/public-ID ordering.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_hazards_are_snapshot_bound_and_deterministic`
- [ ] Stale, unassessed, candidate-heavy, shared-evidence, and snapshot-wide-zero states render with exact affected counts and no numeric coercion.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_hazards_render_observed_states_without_coercion`
- [ ] Snapshot-wide-zero output uses the fixed caveat and makes no claim about scorer defect, missing capability, cause, regression, urgency, or priority.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_snapshot_wide_zero_is_descriptive_not_diagnostic`
- [ ] New renderer-authored interpretation regions contain no ranking, causal, trend, forecast, authoritative, or action-directive rhetoric; the test excludes citations/source text and exempts the exact required non-trend disclaimer.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_new_cockpit_interpretation_copy_avoids_banned_rhetoric`
- [ ] No-hazard and assessment-unavailable fixtures render explicit honest empty/degraded states.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_hazard_empty_and_unavailable_states_are_explicit`
- [ ] The block links to affected capability/detail anchors without changing map ordering or filtering the gaps panel.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_hazard_links_preserve_map_and_gap_order`
- [ ] The implementation PR posts a parent handoff with the exact hazard fixtures and confirms no owner-doc promotion.
  Verify: CKM-DB-02 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Render fixtures for each hazard class, one mixed fixture, one no-hazard fixture, and one
  assessment-unavailable fixture.
- Inspect only nodes marked as renderer-authored interpretation when running banned-rhetoric checks.

## Out of Scope

- Changing scorer formulas, thresholds, linkers, evidence lifecycle, or findings
- Calling a snapshot-wide zero a bug or authorizing a repair
- Ranking capabilities or hazards
- O1b comparison semantics
- Proposal drafts or automatic issue creation

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `app/builderops/ckm/overview_html.py`
- `tests/builderops/ckm/test_overview_html.py`

## Related GitHub Issues

Create one child under the Direction B parent, dependency-blocked on CKM-DB-01. Cheapest acceptable
TCD route: **Terra/high** because generated interpretation can create persuasive false authority and
requires multi-fixture rhetoric scoping; escalate to Sol/high if source-vs-generated-copy boundaries
cannot be isolated deterministically.
