---
name: Receipts History Surface
description: Read-only receipts/history modal over existing runtime-produced receipt projections
task_id: SEP-10
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Surface composition (NORMATIVE table)
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [PANEL_COMMAND_PALETTE.md, SYSTEM_MAP_OVERLAY.md, SETTINGS_DRAWER.md, GUIDANCE_LAYER.md]
---

# Receipts History Surface

## Purpose

Give governed outcomes a place to live beyond a transient toast. Receipts are the trust spine of the Act lane; today they surface in the rail at execution time but have no history view.

## What This Task Does

- Mounts a read-only receipts/history modal on the overlay host (`receipts.open`), reached from the topbar and the system map.
- Renders a bounded list of **existing runtime-produced receipt projections** (outcome — success / blocked / logged / partial / rejected — id, target path/artifact, timestamp), with the shipped receipt-pill semantics and authority colors.
- Strictly read-only: the surface queries existing receipt projections only; it adds no receipt-write path, performs no aggregation the runtime does not declare, and **never invents, edits, or re-derives a receipt**.
- Blocked receipts render with their guard posture per `BLOCKED_AND_STALE_STATE_SPEC.md` — history shows held boundaries as held boundaries, not errors.

## Concretely

```text
receipts.open → modal over the anchor
rows: "receipt · success · note/foo.md · 2026-06-10T09:12Z", "receipt · blocked (WriteGuard) · …"
no action buttons besides inspect/dismiss; Esc → anchor
```

## Why This Matters

A governed system the human cannot audit afterwards degrades into "trust me." History makes the receipt asymmetry inspectable — and a receipts surface with any write affordance would instantly be a new control surface, which the composition forbids.

## Acceptance Criteria

- [ ] The modal renders receipts exclusively from existing runtime receipt projections, with outcome, id, target, and timestamp.
  Verify: `tests/companion_ui/test_receipts_history_surface.py::test_history_renders_runtime_receipt_projections`
- [ ] The surface has no write path: no endpoint call other than reads, no receipt creation, no mutation affordance.
  Verify: `tests/companion_ui/test_receipts_history_surface.py::test_surface_is_strictly_read_only`
- [ ] Blocked receipts render with guard posture, visually distinct from generic errors.
  Verify: `tests/companion_ui/test_receipts_history_surface.py::test_blocked_receipts_render_guard_posture`
- [ ] An empty history renders an honest empty state with no manufactured rows.
  Verify: `tests/companion_ui/test_receipts_history_surface.py::test_empty_history_is_honest`
- [ ] The modal dismisses to the anchor with no route reset.
  Verify: `tests/companion_ui/test_receipts_history_surface.py::test_dismisses_to_anchor`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_receipts_history_surface.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_vault_browser_receipts.py`
- `ruff check app tests`

## Out of Scope

- New receipt query endpoints beyond existing projections (if a bounded read gap is found, raise it on the issue first).
- Receipt retention policy, export, or filtering beyond a bounded recent list.
- Any receipt mutation, annotation, or re-classification.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Authority boundaries ("receipts are never invented")
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md` (receipts row)
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`

## Related GitHub Issues

Filed as **#1794** (`[SystemEntryPoint] receipts-history-surface: read-only receipts modal`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
