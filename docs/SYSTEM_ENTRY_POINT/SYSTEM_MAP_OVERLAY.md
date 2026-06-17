---
name: System Map Overlay
description: User-facing system map overlay with surface nodes (mode, reached → returns) routing to each surface; pull-based, never shown unbidden
task_id: SEP-05
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Resolved Q4
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [PANEL_COMMAND_PALETTE.md, SETTINGS_DRAWER.md, RECEIPTS_HISTORY_SURFACE.md, GUIDANCE_LAYER.md]
---

# System Map Overlay

## Purpose

One place from which the whole companion is legible. The map is the index that composes the existing surfaces — a renderer/router, never a new authority surface and never a dashboard.

## What This Task Does

- Mounts a system map overlay on the overlay host, opened by `map.open` from the topbar in every entry state, and offered as a calm affordance in `cold_start` and `no_vault`.
- Renders the entry-point center node plus one node per composition-table surface, each showing: surface name, product mode (Find / Reorient / Resurface / Act per `docs/COMPANION_UI_PRODUCT_SPEC.md`), how it is reached, how it returns, and its truthful shipped/new status.
- Clicking a shipped surface's node routes to that surface (opens the overlay / focuses the pane); nodes for not-yet-shipped surfaces are present but visibly inert with their status — no dead affordances pretending to work.
- The map is **pull-based**: it never auto-opens, never badges, never surfaces unbidden.
- Parked surfaces (context lane / place band) appear only as a parked note, if at all — they must not render as reachable nodes.

## Concretely

```text
topbar map icon → overlay with center node + surface nodes
node "Vault Browser · Find · reached: left pane · returns: re-anchors" → click → vault pane focused
node for an unshipped surface → rendered with status, not clickable
Esc → anchor
```

## Why This Matters

The companion's knowledge is spread across many surfaces; without a legible index a newcomer (or the owner after a long gap) cannot see the whole. But an auto-surfacing map would be a dashboard — the map must stay sought, not pushed.

## Acceptance Criteria

- [ ] The map renders one node per composition-table surface with mode, reached-as, returns-to, and truthful status.
  Verify: `tests/companion_ui/test_system_map_overlay.py::test_map_renders_composition_table_nodes`
- [ ] Shipped surface nodes route to their surfaces; unshipped nodes are inert and labeled.
  Verify: `tests/companion_ui/test_system_map_overlay.py::test_shipped_nodes_route_and_unshipped_nodes_are_inert`
- [ ] The map is reachable from `cold_start` and `no_vault` as well as `shell_active`.
  Verify: `tests/companion_ui/test_system_map_overlay.py::test_map_reachable_from_cold_and_no_vault_states`
- [ ] The map never renders unbidden: no render path mounts it without an explicit `map.open`.
  Verify: `tests/companion_ui/test_system_map_overlay.py::test_map_never_auto_opens`
- [ ] Parked surfaces (context lane / place band) do not render as reachable nodes.
  Verify: `tests/companion_ui/test_system_map_overlay.py::test_parked_surfaces_not_reachable`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_system_map_overlay.py`
- `pytest -q tests/companion_ui/test_overlay_host.py`
- `ruff check app tests`

## Out of Scope

- Any re-classification of surface authority or status by the map (status text mirrors the spec/owner docs).
- First-run onboarding flows.
- The surfaces the nodes route to (their own tasks).

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q4, §Surface composition
- `docs/COMPANION_UI_PRODUCT_SPEC.md` (mode model)

## Related GitHub Issues

Filed as **#1787** (`[SystemEntryPoint] system-map-overlay: pull-based surface index`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
