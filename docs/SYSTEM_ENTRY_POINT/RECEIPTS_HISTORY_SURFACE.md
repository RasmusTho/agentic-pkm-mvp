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
- **Receipts v2 (#3363, audit `companion-ui/design_handoff/2026-07-07-uat-design-audit/DESIGN_AUDIT.md` §3.2):** the runtime projection (`app/receipts/artifact_receipts.py`) additionally declares `display_verb`, `run_key`, `run_label`, and `target_absolute` for `panel.action.logged`/`panel.action.blocked` rows, with documented fallbacks (`"Recorded"` / `"Run"`) when a record does not declare enough — still never invented by the UI. Rows render grouped under run headers (label + relative time), leading with verb + vault-relative target; the absolute path is hover-only (`title`); the receipt hash and absolute ISO timestamp sit behind a per-row "integrity" disclosure instead of the always-visible row text.

## Concretely

```text
receipts.open → modal over the anchor
Governed capture · 2 min ago
  Appended to   Inbox/inbox.md      ⌄ integrity
  Linked        settings/workflow.md  ⌄ integrity
Vault sync · 14 min ago
  Created       Projects/…/README.md  ⌄ integrity
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
- [x] (#3363) The backend projection declares `display_verb`, `run_key`, `run_label`, and `target_absolute` for `panel.action.logged`/`panel.action.blocked` rows, with documented fallbacks.
  Verify: `tests/receipts/test_artifact_receipts_display_fields.py::test_projection_declares_display_fields`
- [x] (#3363) History rows render grouped under run headers (label + relative time), verb + vault-relative target first, ordered most-recent-first within and across runs.
  Verify: `tests/companion_ui/test_receipts_history_v2.py::test_rows_grouped_by_run`
- [x] (#3363) No absolute filesystem path appears in the always-visible text of a row; the absolute path is reachable via hover/disclosure.
  Verify: `tests/companion_ui/test_receipts_history_v2.py::test_target_paths_vault_relative`
- [x] (#3363) Receipt hash and absolute ISO timestamp are inside a per-row disclosure (`integrity`), not in the always-visible row text.
  Verify: `tests/companion_ui/test_receipts_history_v2.py::test_hash_behind_integrity_disclosure`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_receipts_history_surface.py`
- `pytest -q tests/companion_ui/test_receipts_history_v2.py`
- `pytest -q tests/receipts/test_artifact_receipts_display_fields.py`
- `pytest -q tests/companion_ui/test_vault_browser_receipts.py`
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
