---
name: Render Compatible Observation Comparisons
description: Select the two newest active retained records deterministically and render only the exact O1b comparison or typed refusal.
task_id: CKM-DB-03
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Refusal, degraded, and empty states
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-DB-02]
depends_on: [SURFACE_INTERPRETATION_HAZARDS_HONESTLY.md]
can_parallelize_with: []
---

# Render Compatible Observation Comparisons

## Purpose

Answer the bounded “what differs?” question using the delivered O1b comparison contract, without
silently changing the pair, reconstructing history, or manufacturing trend semantics.

## What This Task Does

- Add a read-only active-sample selector over the existing adjacent
  `<builderops-stem>-metric-samples.sqlite` retention store.
- Select exactly two active rows ordered by `retained_at DESC, sample_id DESC`.
- Invoke `compare_retained_observations` once with those two IDs.
- Render O1b component states/deltas, input sample and observation IDs/digests, freshness,
  provenance, compatibility bindings, limitations, and the exact fixed disclaimer.
- Convert absent/incomplete retention storage, insufficient active rows, expiry/unavailable/tamper,
  corrupt input, and incompatibility into visible typed refusal panels.
- State on every refusal that older retained rows were not searched.

## Concretely

The selector performs one read-only query equivalent to:

```sql
SELECT sample_id
FROM ckm_metric_sample_v1
WHERE lifecycle = 'retained'
ORDER BY retained_at DESC, sample_id DESC
LIMIT 2
```

Zero or one row returns `insufficient_retained_samples` with the observed count. Two rows are passed
unchanged to O1b. If O1b refuses, the cockpit renders that refusal; it does not ask SQLite for a
third row.

Existing real recovery commands are shown only in relevant help text:

```text
python -m app.builderops --db-path <db> ckm measure --retain
python -m app.builderops --db-path <db> ckm compare --sample-id <older> --sample-id <newer>
```

No `ckm observe`, invented capture limit, or automatic retention command may appear.

## Why This Matters

Choosing an older compatible pair after the newest records refuse would answer a different question
while looking successful. Reusing O1b's all-or-nothing result preserves semantic compatibility,
retention honesty, and the distinction between a two-point delta and a trend.

## Acceptance Criteria

- [ ] The production cockpit CLI call selects exactly the newest two active rows by `retained_at DESC, sample_id DESC` using read-only storage and passes those exact IDs to O1b.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_cli_compares_exact_newest_active_retained_pair`
- [ ] If the newest two are incompatible while an older compatible row exists, the cockpit renders `incompatible_observations` and proves the older row was not read or compared.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_does_not_search_older_compatible_pair`
- [ ] Missing/incomplete storage and zero/one active row render typed `source_unavailable` or `insufficient_retained_samples` states without creating or mutating the retention path.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_retention_absent_and_insufficient_states_are_read_only`
- [ ] Expired, unavailable, pruned, deleted, corrupt, or tampered selected input produces the exact O1b refusal with no partial components or fallback.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_selected_source_refusal_is_all_or_nothing`
- [ ] Compatible input renders deterministic component-wise deltas, tagged transitions, bindings, IDs/digests, provenance, freshness, limitations, and “Difference between two snapshots. Not a trend, cause, or forecast.”
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_renders_bound_o1b_delta_and_fixed_disclaimer`
- [ ] A numeric delta appears only when both endpoint states are measured numbers; other transitions keep both tags and no numeric substitute.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_comparison_preserves_tagged_state_transitions`
- [ ] Recovery copy contains only Click commands/flags that exist at the production CLI call site.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_recovery_commands_match_click_help`
- [ ] The implementation PR posts compatible, incompatible-with-older-compatible, unavailable, and insufficient-sample receipts to the parent.
  Verify: CKM-DB-03 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_metric_comparison.py`
- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Exercise the production `ckm overview --cockpit` call with compatible, incompatible, older-
  compatible, insufficient, missing-store, expired, and tampered retention fixtures.

## Out of Scope

- Changing O1b compatibility bindings or retention policy
- Creating or retaining observations during rendering
- Timeline, cadence, trend, cause, forecast, drift, or arbitrary history
- Selecting by user preference or scanning for any compatible pair
- Ranking comparison components

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/COMPARE_COMPATIBLE_OBSERVATIONS.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `app/builderops/ckm/comparison.py`
- `app/builderops/ckm/metrics.py`
- `app/builderops/cli.py`

## Related GitHub Issues

Create one child under the Direction B parent, dependency-blocked on CKM-DB-02. Cheapest acceptable
TCD route: **Sol/high** because this slice touches retained data, compatibility/refusal semantics,
read-side-effect guarantees, and a production CLI boundary; de-escalate implementation mechanics to
Terra/high only after the exact selector/refusal tests are fixed and locally green.
