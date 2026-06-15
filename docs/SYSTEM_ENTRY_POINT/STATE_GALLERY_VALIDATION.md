---
name: State Gallery Validation
description: Fixture-driven validation harness rendering the spec's state gallery against orientation fixtures; final child with parent-closure handoff
task_id: SEP-11
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Validation expectations
parent_capability: system-entry-point
prerequisites: [SEP-01, SEP-02, SEP-03, SEP-04, SEP-05, SEP-06, SEP-07, SEP-08, SEP-09, SEP-10]
depends_on: [ENTRY_STATE_MACHINE.md, REENTRY_ORIENTATION_TREATMENT.md, UNIFIED_TOPBAR_AND_OVERLAY_HOST.md, PANEL_COMMAND_PALETTE.md, SYSTEM_MAP_OVERLAY.md, GUIDANCE_LAYER.md, SETTINGS_DRAWER.md, CAPTURE_TO_VAULT_INBOX.md, MEMORY_REVIEW_DRAWER.md, RECEIPTS_HISTORY_SURFACE.md]
can_parallelize_with: []
---

# State Gallery Validation

## Purpose

Prove the composition as a whole: render every state the spec declares from fixtures, assert every invariant the spec's Validation-expectations section names, and close the parent capability truthfully.

## What This Task Does

- Builds a fixture-driven harness (extending the existing fixture approach in `tests/companion_ui/fixtures/` and the orientation fixtures) that renders the handoff package's state gallery — entry states A1–A7, shell states B1–B12, responsive C1, guidance E, and the settings/read-back/capture/receipts F-states that shipped — against fixture orientation snapshots.
- Asserts, across the gallery:
  - every declared entry-point transition renders, and undeclared transitions are rejected;
  - no UI-derived posture/class/authority anywhere;
  - cold (>14d), first contact, and `no_vault` show no re-entry overlay;
  - governed intents surface receipts; body edits do not (receipt asymmetry);
  - blocked/stale render as guard-held states;
  - the display budget caps visible items at or below server caps;
  - reduced-motion renders every end-state fully visible;
  - narrow/portrait preserves every critical affordance.
- Owns the fixture set (the spec explicitly delegates it here).
- **Parent-closure handoff**: posts the final validation receipt to the parent feature issue; updates the spec's shipped-vs-new statuses, `docs/STATUS.md`, and this directory's `README.md`/`PARENT_FEATURE_ISSUE.md` state lines so the capability reads as delivered; or, if residual gaps remain, files the explicit follow-up issues and records them on the parent before it closes.

## Concretely

```text
pytest tests/companion_ui/test_entry_state_gallery.py
  → parametrized over gallery fixtures: every state renders, every MUST-NOT holds
```

## Why This Matters

Each child proves its slice; nothing else proves the composition. The gallery harness is also the regression net that keeps later UI work from silently violating the entry/overlay grammar.

## Acceptance Criteria

- [ ] Every state declared in the spec's gallery renders from a fixture with its declared `data-entry-state` / regions present.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_state_gallery_renders_all_declared_states`
- [ ] Undeclared entry transitions are rejected across the fixture matrix.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_undeclared_transitions_rejected_across_fixtures`
- [ ] Cold, first-contact, and no-vault fixtures contain no re-entry overlay region.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_cold_and_no_vault_have_no_reentry_overlay`
- [ ] Governed-vs-body-edit receipt asymmetry holds across the gallery.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_governed_vs_body_edit_receipt_asymmetry`
- [ ] No fixture render contains UI-derived authority classification (all classes traceable to fixture-declared fields).
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_no_ui_derived_authority`
- [ ] Display-budget, reduced-motion, and narrow-parity assertions pass across the gallery.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_budget_reduced_motion_and_narrow_parity`
- [ ] Parent-closure handoff executed: validation receipt on the parent issue, spec/status/README state lines updated to delivered reality.
  Verify: parent feature issue closing comment + docs writeback diff (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`, `docs/STATUS.md`, `docs/SYSTEM_ENTRY_POINT/README.md`, `docs/SYSTEM_ENTRY_POINT/PARENT_FEATURE_ISSUE.md`)

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_entry_state_gallery.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/` (full surface suite stays green)
- `ruff check app tests`

## Out of Scope

- New behavior — this task adds fixtures and assertions, not surfaces.
- Visual-regression screenshot tooling (may be proposed separately).
- Validating the parked context lane / place band.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Validation expectations
- `companion-ui/design_handoff/2026-06-09-system-entry-point/state-gallery.md` and `edge-states.md` (gallery source, guidance only)
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md` §Cognitive-load state extension (fixture naming)

## Related GitHub Issues

Filed as **#1795** (`[SystemEntryPoint] state-gallery-validation: fixture-driven composition proof + parent closure`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
