---
name: Freshness / as_of / trace_id in topbar disclosure and map entry-point node
description: Expose the deleted "Re-entry snapshot" meta row fields (freshness, as_of, trace_id) as read-only projection in the topbar runtime-status disclosure and in the system-map entry-point node
task_id: TELEMETRY_RELOCATION-01
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [NOTABLE_CHANGES_ORIENTING_DELTA_STRIP.md]
---

# Freshness / as_of / trace_id in topbar disclosure and map entry-point node

## Purpose

The "Re-entry snapshot" h1 + meta row (`freshness`/`as_of`/`trace_id`) was removed from `cold_start` by #2171. An operator who relied on those fields for runtime diagnostics must still have a pull path. The spec mandates both the topbar runtime-status disclosure and the system-map entry-point node as the two relocation targets — "kept in both so an operator diagnostic is never stranded" (open-questions.md Q3).

## What This Task Does

1. Confirm (or add) `freshness`/`as_of`/`trace_id` rows in the `workspace-runtime-status-popover` `<details>` block (`serve_dev_page.py` `_render_workspace_header`) with `data-authority="read-only-projection"`.
2. Extend the system-map entry-point center node (`system_map_overlay.py` `MAP_CENTER_NAME`/`MAP_CENTER_SUB` or a dedicated `entry_point_meta_html` helper) to render these three fields as a read-only terse mono row when present in the orientation payload.
3. Confirm neither rendering appears on `cold_start` (the header is gated; the map only opens on explicit `map.open`).
4. Add/update the two named tests.

## Concretely

```bash
# After the change, with a live runtime:
# topbar runtime-status popover carries a row with data-testid="workspace-freshness-as-of"
# system-map entry-point node carries data-testid="map-entry-point-freshness"
pytest -q tests/companion_ui/test_system_map_overlay.py::test_entry_point_map_and_runtime_status_render_relocated_telemetry
pytest -q tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Why This Matters

If these fields are only deleted and not relocated, a developer or operator has no pull path to verify `freshness` / `trace_id` on `cold_start` — the only diagnostic that confirms the runtime snapshot age. The spec's open-questions.md Q3 explicitly gates the header deletion on verifying both pull paths render the values.

## Acceptance Criteria

- [ ] The topbar runtime-status popover (`data-testid="workspace-runtime-status-popover"`) renders `freshness`, `as_of`, and `trace_id` as read-only mono rows with `data-authority="read-only-projection"` when the orientation payload supplies them.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_entry_point_map_and_runtime_status_render_relocated_telemetry`
- [ ] The system-map entry-point center node renders the same three fields as a terse read-only projection row with `data-authority="read-only-projection"` when present; omitted when absent.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_entry_point_map_and_runtime_status_render_relocated_telemetry`
- [ ] Neither rendering appears on `cold_start` outside the pull-only surfaces (map requires explicit `map.open`; topbar popover requires explicit `<details>` open — neither auto-open).
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] Zero-state: when the orientation payload omits `freshness`/`as_of`/`trace_id`, neither projection renders a placeholder row.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_system_map_overlay.py::test_entry_point_map_and_runtime_status_render_relocated_telemetry \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

All three named tests must pass (they will be new tests written by the implementing agent).

## Out of Scope

- Changing the `workspace_freshness` label (the existing `<span class="workspace-freshness">` in the topbar row) — that is a separate rendering element; this task adds fields to the `<details>` popover only.
- Interactive controls on the topbar disclosure (read-only only).
- Any change to the `orienting`/`shell_active` header path (unchanged).

## Restart / Durability Posture

The topbar disclosure and map entry-point node are server-rendered read-only projections. No state survives a process restart beyond what the orientation payload supplies. If the runtime is unreachable (`no_vault`), both surfaces omit the freshness row honestly — no placeholder, no stale value displayed.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door
- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/open-questions.md` Q3, Q6
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py`
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_render_workspace_header`, `telemetry_rows`)

## Related GitHub Issues

Parent: #2174. One implementation issue for this task; depends on nothing; can parallelize with NOTABLE_CHANGES_ORIENTING_DELTA_STRIP.
