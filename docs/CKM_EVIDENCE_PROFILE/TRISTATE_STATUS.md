---
name: Per-Dimension Tri-State and Documentation-Scorer Fix
description: Add an additive JSON dimension_status column adopting SUPPORTED_VALUE_STATES, make per-dimension unassessed a first-class render state, and fix the documentation empty-set to unassessed with a formula-id bump.
task_id: CKM-EP-02
source_anchor: docs/CKM_EVIDENCE_PROFILE/README.md :: Phase boundary (what Phase 1 is and is not)
parent_capability: CKM Evidence Profile
prerequisites: [CKM-EP-01]
depends_on: [SCALAR_RETIREMENT.md]
can_parallelize_with: []
---

# Per-Dimension Tri-State and Documentation-Scorer Fix

## Purpose

Today a dimension with zero score and no citations ("evidence-starved") is indistinguishable in data
from a dimension that was never assessed; the render only reaches an `unassessed` state when the whole
assessment is `None`. This task makes per-dimension `unassessed` a first-class, additively-persisted
state and fixes the documentation scorer, which currently returns a hard `0.0` on an empty
documentation-evidence set — rendering "starved" when the honest answer is "unassessed". It stays
zero-DDL.

## What This Task Does

- Add an additive JSON `dimension_status` column to `ckm_assessment` using the **4-place additive
  pattern**, with **no `CKM_SCHEMA_VERSION` bump**:
  1. add the column to the `CREATE TABLE ckm_assessment` DDL in `app/builderops/ckm/schema.py`;
  2. register it in `CKM_REQUIRED_COLUMNS["ckm_assessment"]`;
  3. register it in `CKM_LEGACY_ADDED_COLUMNS["ckm_assessment"]` so pre-existing databases pass the
     "required minus legacy-added" preflight (`store.py`);
  4. back-fill existing rows idempotently via `ALTER TABLE ckm_assessment ADD COLUMN dimension_status
     TEXT NOT NULL DEFAULT '{}'` in a `store.py` migration mirroring
     `_migrate_assessment_explainability`, and write/read the column in
     `store.append_assessment` and the assessment row reader.
- Adopt the `app/builderops/ckm/contracts.py` `SUPPORTED_VALUE_STATES` vocabulary
  (`measured` / `missing` / `unassessed` / `unsupported`) for `dimension_status` values; scores stay
  float-valued (the status column tags absence semantics alongside the score, it does not replace it).
- Teach the overview render the per-dimension `unassessed` state:
  - `_mini_dimensions_markup` must emit an `unassessed` mini-cell for a dimension whose status is
    `unassessed`, not only when the whole assessment is `None`;
  - `_dimension_markup` must render an `unassessed` expanded state (dash, no score/fill) distinct from
    the evidence-starved dotted-zero treatment.
- Fix `_documentation` in `app/builderops/ckm/assess.py`: on the empty selected-documentation set,
  record `unassessed` (drive `dimension_status`) instead of returning `DimensionResult(0.0, ())`, and
  **bump the formula id** `current-doc-evidence-v1` → `current-doc-evidence-v2` (register the v2
  `Formula` in `FORMULAS` and update `_DIMENSION_FORMULA_IDS["documentation_quality"]`).

## Concretely

A capability with no documentation evidence renders, for the DOC dimension, an `unassessed` dash
rather than a starved zero:

```
DOC  —   (unassessed — no documentation evidence)
```

The stored assessment carries `dimension_status = {"documentation_quality": "unassessed", …}` and
`formula_ids["documentation_quality"] = "current-doc-evidence-v2"`. A legacy database created before
this task opens without error: the migration adds `dimension_status` with default `'{}'`, and the
formula-id change means the next `assess` run re-mints affected assessments as new bitemporal rows.
`CKM_SCHEMA_VERSION` stays `5`.

## Why This Matters

Without the formula-id bump (INV-EP-3), `assessment_fingerprint` treats a re-run as unchanged and
**skips** it, so old starved-zero documentation assessments never get re-computed and the false
"starved" render persists — the fix would silently no-op. Without the additive column, per-dimension
`unassessed` has nowhere to live and the render cannot tell absence from measured zero (the exact
confusion the tri-state is meant to remove). A schema-version bump would trip #3775/#3777's
version-mismatch refusal, so the column must be additive.

## Acceptance Criteria

- [ ] `dimension_status` is added to `ckm_assessment` via the 4-place additive pattern and a legacy
  database (created before this task) opens and back-fills without error; `CKM_SCHEMA_VERSION` is
  unchanged at `5`.
  Verify: `tests/builderops/ckm/test_store.py` additive-column round-trip + legacy-DB back-fill test asserting the column exists, defaults, and the schema version is unchanged.
- [ ] `dimension_status` values are constrained to the `SUPPORTED_VALUE_STATES` vocabulary and round-
  trip through `store.append_assessment` and the row reader.
  Verify: `tests/builderops/ckm/test_store.py` asserts persisted `dimension_status` values are a subset of `contracts.SUPPORTED_VALUE_STATES`.
- [ ] The mini-cell grid and the expanded dimension markup render a per-dimension `unassessed` state
  (dash, no score/fill) distinct from evidence-starved zero, driven by `dimension_status` rather than
  by the whole assessment being `None`.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_dimension_cells_render_three_states_and_proportional_fill` extended so a single dimension can render `unassessed` while its siblings are scored.
- [ ] `_documentation` records `unassessed` (not `0.0`) on the empty documentation-evidence set and
  reports formula id `current-doc-evidence-v2`.
  Verify: `tests/builderops/ckm/test_assessment_engine.py` documentation-empty-set case asserts `unassessed` status + `current-doc-evidence-v2`.
- [ ] The documentation formula-id bump forces re-assessment: a store whose documentation assessment
  used `current-doc-evidence-v1` re-mints a new assessment row on the next `assess` run rather than
  being skipped by the fingerprint check.
  Verify: `tests/builderops/ckm/test_assessment_engine.py` asserts a new assessment row is appended when only the documentation formula id changed.
- [ ] Render stays pure, deterministic, read-only, and self-contained after the tri-state edits.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `::test_cli_rejects_missing_database_without_creating_it`; `::test_no_scripts_or_external_references`.
- [ ] Shared real-store validation gate (INV-EP-6): the real 31-capability store renders per-dimension
  `unassessed` where evidence is genuinely absent, not a false starved zero.
  Verify: real-store replay receipt on the coordinator-filed parent feature issue.

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_store.py tests/builderops/ckm/test_assessment_engine.py tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q -m "not pg" tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Open a pre-task fixture database and confirm the migration adds `dimension_status` idempotently
  (re-run leaves it unchanged) and the schema version is still `5`.
- Real-store replay (mac mini): confirm genuinely-absent dimensions render `unassessed`, and attach
  the receipt to the parent feature issue.

## Out of Scope

- Removing the aggregate/band render (CKM-EP-01, prerequisite).
- The per-subsystem counts view (CKM-EP-03).
- Any dimension merge/rename, stub scorers, or the `intent_realization` / `tested_surface` reshape
  (Phase 2). Only `documentation_quality`'s empty-set semantics change here.
- Dropping the `aggregate` column or any `CKM_SCHEMA_VERSION` change.

## Restart / Durability Posture

The additive `dimension_status` column is durable SQLite state, not deferred/in-memory: it survives
restart, and the migration is idempotent so a restart mid-migration is safe to retry (INV-CKM-7). The
overview render remains a pure regeneration from that durable store; no reviewed-state-in-memory
trust consequence exists.

## Related Docs

- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` (three cell-state contract: scored / evidence-starved / unassessed)
- `app/builderops/ckm/schema.py`, `app/builderops/ckm/store.py`, `app/builderops/ckm/assess.py`, `app/builderops/ckm/contracts.py`, `app/builderops/ckm/overview_html.py`

## Related GitHub Issues

Not yet filed. The coordinator creates this slice from the merged spec. May be delivered jointly with
CKM-EP-01 in one issue/PR (shared overview render surface and real-store gate). Point `Context` at the
parent feature issue and reference "Implements CKM_EVIDENCE_PROFILE/TRISTATE_STATUS". TCD hint:
Sonnet / high — additive schema migration plus the formula-id/fingerprint coupling is the correctness-
sensitive part (a missed bump silently no-ops the fix); escalate if the migration or fingerprint
interaction proves subtler than the existing `_migrate_assessment_explainability` precedent.
