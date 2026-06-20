---
name: Resurface candidates to rail mode and map node
description: Relocate resurface candidates from the cold_start door to the resurface rail mode (shell) and a mode-labelled map node; reached only by explicit pull, never unbidden
task_id: TELEMETRY_RELOCATION-05
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [OPEN_LOOPS_MEMORY_NODE_AND_PANEL_RAIL.md]
---

# Resurface candidates to rail mode and map node

## Purpose

Resurface candidates were on the `cold_start` orientation grid. The design notes specify the destination as "Resurface rail mode (shell) + mode-labelled map node; reached only by explicit pull, never unbidden on entry." The design-notes also note that `_render_resurface_mode`'s source link is inert text (not a click handler) — this relocation does NOT fix that rendering bug (filed separately), it only ensures resurface candidates no longer appear on `cold_start`.

## What This Task Does

1. Confirm `_render_orientation_resurface` is not called for `cold_start` in `_render_orientation_index_html` (already gated by #2171's branch; this task adds a test assertion).
2. In `system_map_overlay.py`, add a `resurface` `MapNode` with mode `("resurface",)`, label "Resurface candidates", reached via the shell resurface rail mode, status `shipped` (the `_render_resurface_mode` function exists in `serve_dev_page.py`). The node is inert (non-routable in the map index; the resurface rail is reached by user navigation, not by `overlayHost.mount`).
3. Add/update the named tests.

## Concretely

```bash
pytest -q \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Why This Matters

Without a map node declaring "resurface is a pull mode in the shell," an operator on `cold_start` has no map-legible path to resurface candidates after the grid is removed. The map node is the index entry; the actual resurface rendering stays on the `shell_active` rail path where it was already shipped.

## Acceptance Criteria

- [ ] No resurface candidates region, `_render_orientation_resurface` output, or `+N more` resurface overflow appears in the `cold_start` HTML render.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] A `resurface` `MapNode` appears in `MAP_SURFACES` with `mode=("resurface",)` and `status="shipped"` (or `"partial"` if the rail mode's routing contract is incomplete); node is plainly inert in the map index (no `overlayHost.mount` route — the rail is navigated in the shell, not mounted as an overlay).
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] The resurface map node does not auto-route or badge; it is an index entry only.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] The `shell_active` resurface rail path (`_render_resurface_mode`, `serve_dev_page.py`) is unmodified and continues to pass its existing tests.
  - Verify: `tests/companion_ui/test_reentry_orientation_surface.py` (existing; must remain green)

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions \
  tests/companion_ui/test_reentry_orientation_surface.py
```

`test_reentry_orientation_surface.py` (existing) must remain green — no regression to the `shell_active` resurface path.

## Out of Scope

- Fixing the inert `data-source-link` / missing click handler bug in `_render_resurface_mode` (separate issue; do not bundle).
- Making the resurface map node routable via `overlayHost.mount` (the resurface rail is a shell mode, not an overlay occupant).
- Any change to the `orienting`/`shell_active` resurface rendering (unchanged by design).

## Restart / Durability Posture

The resurface rail is server-rendered from the orientation payload's `resurface_candidates`. A process restart resets to whatever the next payload supplies. The map node is a static index entry (no runtime state). No durability concern.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door (incl. the note on `_render_resurface_mode`'s inert source link)
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_render_orientation_resurface`, `_render_resurface_mode`)
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`

## Related GitHub Issues

Parent: #2174. One implementation issue; can parallelize with OPEN_LOOPS_MEMORY_NODE_AND_PANEL_RAIL. No prerequisites.
