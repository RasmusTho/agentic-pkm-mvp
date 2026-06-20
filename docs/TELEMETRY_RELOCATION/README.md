---
name: Telemetry Relocation — Pull-Only Surfaces
description: Relocate governance/open-loops/notable-changes/resurface/freshness telemetry off the cold_start door into pull-only surfaces
state: delivery — child issues filed; #2174 is the live validation hub
parent_issue: "#2174"
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
---

# Telemetry Relocation — Pull-Only Surfaces

## Purpose

Recomposing `cold_start` removes the "Re-entry snapshot" header, the telemetry meta row, and the orientation grid from the front door (done via #2171/#2172/#2176). The six data projections that lived on that door must remain reachable — but as **pull-only, read-only projection, counts-not-tiles, no zero-state** — never as live dashboard tiles (or the dashboard is re-created one layer deeper).

This specification defines the six bounded relocation tasks, one per destination surface group, and the cross-task invariant that none of them must ever become interactive tiles.

## Design authority

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § "What moves off the door (→ pull-only surfaces)"
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` (anti-dashboard posture)
- `companion-ui/docs/REENTRY_ORIENTATION_TREATMENT.md`

## Relocation table (normative basis)

| Removed from `cold_start` | Destination | Rendering rule |
|---|---|---|
| `"Re-entry snapshot"` h1 + meta row (`freshness`/`as_of`/`trace_id`) | System map entry-point node AND topbar runtime-status disclosure | read-only projection |
| Governance 3-cell grid (proposals/receipts/outcome) | Receipts surface + map governance node | read-only projection, not live tiles, no zero-state |
| Open-loops list/counts | Memory-review map node + document panel rail (once a note is open) | counts-not-tiles |
| Notable-changes list | `orienting` long-mist delta strip only | never manufactured for empty `cold_start` |
| Resurface candidates | Resurface rail mode (shell) + mode-labelled map node | reached only by explicit pull |
| `_reentry_counts` aggregate | full-mist/long-mist re-entry card in `orienting` | counts imply a trajectory `cold_start` cannot back |

## Task files (execution order)

1. `FRESHNESS_TOPBAR_AND_MAP_NODE.md` — expose freshness/as_of/trace_id in topbar runtime-status disclosure and system-map entry-point node
2. `GOVERNANCE_RECEIPTS_AND_MAP_NODE.md` — governance counts → receipts surface + map governance node (read-only projection)
3. `OPEN_LOOPS_MEMORY_NODE_AND_PANEL_RAIL.md` — open-loop counts → memory-review map node + document panel rail
4. `NOTABLE_CHANGES_ORIENTING_DELTA_STRIP.md` — notable-changes → orienting long-mist delta strip (gate: omit from `cold_start`)
5. `RESURFACE_RAIL_AND_MAP_NODE.md` — resurface candidates → resurface rail mode + map mode-labelled node
6. `REENTRY_COUNTS_ORIENTING_CARD.md` — `_reentry_counts` aggregate → full-mist/long-mist re-entry card in `orienting`

Tasks 4 and 6 are purely gating/suppression tasks (ensure the data does not appear on `cold_start`); Tasks 1–3 and 5 are relocation tasks (add the projection to a new pull surface). Tasks can be parallelized in pairs (1+4, 2+6, 3+5 share no render-path conflicts), but task 6 should be confirmed after 4 since both touch `orienting` render paths.

## Out of scope

- Multi-vault epic (#2143)
- The `cold_start` render itself (already shipped via #2171/#2172/#2176)
- The orientation grid path for `orienting`/`shell_active` (unchanged by design)
- New interactive dashboard tiles anywhere (hard constraint — the anti-dashboard rule)

## Cross-Task Invariants / Interaction Safety

**Invariant 1 — No zero-state**: None of the six relocation tasks may render a count or projection when the underlying collection is empty. A zero-filled projection is a dashboard tile. Every task file's AC carries an explicit "no zero-state" check.

**Invariant 2 — Read-only projection only**: Relocated telemetry carries `data-authority="read-only-projection"` and emits no mutation intent. The receipts surface (Task 2) is already read-only; the map nodes (Tasks 1, 2, 3, 5) are index nodes with no write affordance. Panel rail open-loops display (Task 3) is a counts badge only.

**Invariant 3 — Suppression on cold_start is gated before relocation renders**: Tasks 4, 6, and the suppression AC in Task 1 must confirm the data does not appear on `cold_start` before the relocation target adds it elsewhere. Partial failure path: if Task 1 adds freshness to the topbar disclosure but the cold_start header is not yet gated, the header may still render — verify suppression AC first in each PR.

**Invariant 4 — Map stays pull-only**: No task may cause the system map to auto-open, badge, or surface unbidden. Map node additions (Tasks 1, 2, 3, 5) are inert read-only index expansions, not new interactive regions.

**Partial-failure path**: A task that adds a projection to a pull surface but does not verify the cold_start suppression AC in the same PR risks exposing telemetry in two places simultaneously. Both the "add to pull surface" and "confirm absent from cold_start" ACs must pass before a child PR merges.

## Validation / Acceptance Path

Parent issue #2174 is the live validation hub. After each child merges:
1. Run `pytest -q tests/companion_ui/test_system_map_overlay.py tests/companion_ui/test_reentry_orientation_treatment.py tests/companion_ui/test_receipts_history_surface.py`
2. Post a validation receipt comment to #2174 naming the merged PR and the tests that passed.
3. When all six children are done and green, #2174 can be closed.

## Relationship to GitHub Issues

- Parent: #2174 (validation hub — do not close until all children accepted)
- Children: filed from each task file below; see individual task files for issue numbers once created.
