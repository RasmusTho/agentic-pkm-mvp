---
name: Open-loops counts to memory-review map node and document panel rail
description: Relocate open-loop counts from the cold_start door to the memory-review map node (as an index count) and to the document panel rail badge (once a note is open)
task_id: TELEMETRY_RELOCATION-03
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [RESURFACE_RAIL_AND_MAP_NODE.md]
---

# Open-loops counts to memory-review map node and document panel rail

## Purpose

The open-loops list/counts were on the `cold_start` door. The design notes specify: "loops belong to a trajectory; legitimately none on first contact." The two pull-only destinations are the memory-review map node (as an index count badge on the node row) and the document panel rail (as a counts badge, visible only once a note is open in `shell_active`).

## What This Task Does

1. In `system_map_overlay.py`, extend the `memory` `MapNode` to accept and render an `open_loops_count` from the orientation payload as a terse read-only annotation (`data-testid="map-memory-node-open-loops-count"`, `data-authority="read-only-projection"`); omitted when zero or absent.
2. In the `shell_active` panel rail render path (`serve_dev_page.py`), add an open-loops count badge (`data-region="panel-rail-open-loops"`, `data-authority="read-only-projection"`) when the orientation payload supplies a non-zero `open_loops` count and the shell is in `shell_active`. The badge routes to `memory.open` on click (already a shipped intent).
3. Confirm open-loops list/counts are entirely absent from `cold_start` render output.
4. Add/update the named tests.

## Concretely

```bash
pytest -q \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Why This Matters

Open loops are cognitive objects tied to an active trajectory. Showing them on `cold_start` implies a trajectory the system cannot back. Moving them to the memory drawer (pull-only) and the panel rail (context-appropriate — only when a note is open) places them at the right cognitive moment.

## Acceptance Criteria

- [ ] The memory-review map node renders an open-loops count annotation (`data-testid="map-memory-node-open-loops-count"`, `data-authority="read-only-projection"`) when the orientation payload supplies a non-zero `open_loops` count.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] The open-loops count annotation on the map node is omitted when `open_loops` count is zero or absent (no zero-state).
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] In `shell_active`, the panel rail renders an open-loops count badge (`data-region="panel-rail-open-loops"`, `data-authority="read-only-projection"`) when `open_loops` count is non-zero; omitted otherwise.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] No open-loops list, count, or `_render_orientation_open_loops` output appears in the `cold_start` render.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] The panel rail open-loops badge is a counts-not-tiles display: no list of loop items, no interactive loop management controls.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Out of Scope

- The open-loops *list* (individual loop items) — counts-not-tiles only; the list belongs to the memory review drawer's scope.
- Open-loop CRUD or management (those are governed operations in the memory review drawer).
- Surfacing open-loops on `orienting` (the design notes do not route them there; orienting has its own trajectory-appropriate shape).

## Restart / Durability Posture

Open-loop counts are runtime-read from the orientation payload. A process restart resets to whatever the next orientation response supplies. If the panel rail badge showed "3 open loops" before restart and the next orientation returns 0, the badge correctly disappears — no stale badge persists.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py` (`memory` MapNode)
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_render_orientation_open_loops`)
- `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py`

## Related GitHub Issues

Parent: #2174. One implementation issue; can parallelize with RESURFACE_RAIL_AND_MAP_NODE. No prerequisite.
