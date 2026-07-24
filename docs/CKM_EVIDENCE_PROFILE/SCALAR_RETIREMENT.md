---
name: Retire the Cross-Dimension Scalar from Render
description: Remove the aggregate/band render from the CKM overview and Markdown projections so the per-dimension vector is the display; keep the aggregate column written (zero-DDL).
task_id: CKM-EP-01
source_anchor: docs/CKM_EVIDENCE_PROFILE/README.md :: Phase boundary (what Phase 1 is and is not)
parent_capability: CKM Evidence Profile
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Retire the Cross-Dimension Scalar from Render

## Purpose

The render-time cross-dimension aggregate (minimum of seven weighted dimension scores) drives a
`critical` maturity band that paints ~31 capability boxes red regardless of the evidence that
actually exists. This task removes the aggregate and band from every render surface so the honest
per-dimension vector becomes the display. It is the first Phase-1 package because it — not the counts
view or the tri-state work — is the mechanism that removes the false picture.

## What This Task Does

- Remove the aggregate/band render from `app/builderops/ckm/overview_html.py`:
  - delete `_band()` and its `critical < 0.4` / `watch < 0.7` / `healthy` thresholds;
  - remove the `min {value}` chip (`<span class="aggregate" title="Minimum of seven maturity
    dimensions">min …</span>`), the `band-{band}` class and `data-aggregate-band` attribute on the
    capability `<article>`, and the `<span class="band-label">…</span>` dot-plus-word band encoding;
  - remove the now-dead `aggregate` / `band` locals in `_capability_markup` and the band CSS classes
    (`.band-critical`, `.band-watch`, `.band-healthy`, `.band-dot` variants).
- Remove the aggregate rendering from `app/builderops/ckm/projections.py`: the "aggregate convenience
  score **{value}** (`{formula_id}`)" line in the multi-capability projection and the "aggregate
  convenience score **{value}**" line in the single-capability projection.
- **Keep `compute_aggregate` computing and writing** the NOT-NULL `aggregate` and
  `aggregate_formula_id` columns in `assess.py` / `store.append_assessment`. The column becomes dead
  data (no removal is authorized by this directory); leaving the write in place is what keeps this task
  zero-DDL. Nothing renders it.
- Bundle the presentation-contract writeback: update the acceptance rows in
  `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` that require the subordinate `min`
  aggregate and the text-and-shape maturity band (its rows 5 and 22, the band-encoding language, and
  the CKM11 criteria that reference `min`/band) in the same PR as the render change.

## Concretely

Before, a collapsed Retrieval capability renders:

```
Retrieval   [mini cells]   min 0.00   ● critical   node: confirmed
```

After, the same capability renders its per-dimension vector with no aggregate and no band:

```
Retrieval   [mini cells]   node: confirmed
```

The stored assessment row is unchanged — `SELECT aggregate, aggregate_formula_id FROM ckm_assessment`
still returns the computed `min` value and `aggregate-weighted-min-v1`; only the render stops reading
it. `CKM_SCHEMA_VERSION` stays `5`.

## Why This Matters

If the scalar keeps rendering, the counts view and the tri-state work both ship on top of a page that
still colours 31 boxes red off the min-aggregate — the headline promise of the redesign (an honest
picture) would be false. The band render, not the stored score, is the mechanism; removing it at the
render layer is both sufficient and zero-DDL. Retiring the stored column instead would require a
schema epoch, which Phase 1 explicitly forbids (INV-EP-1).

## Acceptance Criteria

- [ ] The HTML overview renders no maturity band and no aggregate chip: no `band-*` class, no
  `data-aggregate-band` attribute, no `min …` chip, no `band-label`.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_aggregate_demoted_label` updated/renamed to assert the `min` chip and band markup are absent.
- [ ] The Markdown projections render no "aggregate convenience score" line in either the
  multi-capability or single-capability projection.
  Verify: `tests/builderops/ckm/test_projections.py` aggregate-line assertions updated to assert absence.
- [ ] `compute_aggregate` still runs and the `aggregate` / `aggregate_formula_id` columns are still
  written NOT-NULL on every new assessment; `CKM_SCHEMA_VERSION` is unchanged at `5`.
  Verify: `tests/builderops/ckm/test_assessment_engine.py::test_aggregate_transparent_and_min_capped` still passes; `tests/builderops/ckm/test_store.py` assessment round-trip still asserts the column is populated.
- [ ] Render stays pure, deterministic, read-only, and self-contained after the removal.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `::test_cli_rejects_missing_database_without_creating_it`; `::test_no_scripts_or_external_references`.
- [ ] The Direction A acceptance rows that require the `min` aggregate / maturity band are updated in
  this PR.
  Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md :: Acceptance criteria` present in the CKM-EP-01 PR diff.
- [ ] Shared real-store validation gate (INV-EP-6): replaying `seed → ingest → link → assess →
  overview` on the operator's real 31-capability store shows Retrieval no longer rendering falsely red
  / `critical`.
  Verify: real-store replay receipt on the coordinator-filed parent feature issue.

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py tests/builderops/ckm/test_projections.py tests/builderops/ckm/test_assessment_engine.py`
- `python3 -m pytest -q -m "not pg" tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Regenerate the overview against a fixture store and confirm by inspection that no capability carries
  a band class or `min` chip.
- Real-store replay (authorized runtime host, where real DB access exists): run the pipeline against the operator's
  31-capability store and attach the Retrieval-not-red receipt to the parent feature issue.

## Out of Scope

- The per-dimension `unassessed` tri-state and the documentation-scorer fix (CKM-EP-02).
- The per-subsystem counts view (CKM-EP-03).
- Dropping the `aggregate` column or any schema-version change; the superseded Phase-2 package no
  longer authorizes that work.
- Any dimension merge/rename or the maturity→evidence-profile reframe; each requires a separate
  future specification, authority decision, and issue contract.

## Restart / Durability Posture

Not applicable in the trust sense: the overview is a generated static artifact regenerated from the
CKM store on every render, and this task removes render output only. No new deferred or in-memory
state is introduced; a process restart changes nothing about what the next render produces.

## Related Docs

- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `app/builderops/ckm/overview_html.py`, `app/builderops/ckm/projections.py`, `app/builderops/ckm/assess.py`

## Related GitHub Issues

Filed as [#4090](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4090), the first serial child
of parent validation hub [#4089](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089). It is
delivered independently before CKM-EP-02; its exact PR/SHA, validation, owner-doc result, and parent
handoff belong on #4089. TCD hint: Sonnet / medium — bounded render-surface deletion mirroring an
existing pattern, low blast radius, but the Direction A contract writeback and the real-store gate
must not be dropped at handoff.
