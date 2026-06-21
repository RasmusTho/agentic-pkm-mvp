---
name: Governance counts to receipts surface and map governance node
description: Relocate the cold_start governance 3-cell grid (pending proposals / pending receipts / latest receipt outcome) to the receipts surface as counts-not-tiles and to a map governance index node, read-only projection, no zero-state
task_id: TELEMETRY_RELOCATION-02
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [REENTRY_COUNTS_ORIENTING_CARD.md]
---

# Governance counts to receipts surface and map governance node

## Purpose

The governance 3-cell grid (pending proposals / pending receipts / latest receipt outcome) was removed from the `cold_start` door. Governance projection data is legitimate diagnostic information, but it must not re-appear as live interactive tiles. The two pull-only destinations are: the existing receipts surface (as a read-only summary header, not a new tile region) and a new map governance index node (read-only, inert unless the receipts surface is routable).

## What This Task Does

1. In `receipts_history.py` (the shipped receipts history surface, #1794), add a governance-summary read-only row at the head of the modal (`data-region="governance-counts"`, `data-authority="read-only-projection"`) showing pending proposal count, pending receipt count, and latest receipt outcome when the orientation payload supplies `governance.*`. Omitted when absent or when both counts are zero and no meaningful latest outcome exists.
2. In `system_map_overlay.py`, add a `governance` `MapNode` (status `shipped` once this lands) with mode `("act", "reorient")`, reached via `receipts.open` (routes to the receipts surface which now carries governance counts), inert when absent.
3. Add the node to `MAP_SURFACES` in dependency order (after `receipts` node, which is already present).
4. Add/update the named tests.

## Concretely

```bash
pytest -q \
  tests/companion_ui/test_receipts_history_surface.py::test_governance_counts_render_as_read_only_projection \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Why This Matters

Governance receipts and proposals are a key operator diagnostic. Stranding them behind no pull path after the cold_start grid is removed means a returning operator has no way to know about pending governance outcomes without navigating to a specific document. The receipts surface is the natural home (it already renders receipts read-only).

## Acceptance Criteria

- [ ] The receipts history modal renders a governance counts row (`data-region="governance-counts"`, `data-authority="read-only-projection"`) showing `pending_proposal_count`, `pending_receipt_count`, and `latest_receipt_outcome` when the orientation payload's `governance` object supplies them.
  - Verify: `tests/companion_ui/test_receipts_history_surface.py::test_governance_counts_render_as_read_only_projection`
- [ ] The governance counts row is omitted when the orientation payload supplies no governance data or both pending counts are zero and `latest_receipt_outcome` is absent/empty/non-meaningful (no zero-state).
  - Verify: `tests/companion_ui/test_receipts_history_surface.py::test_governance_counts_render_as_read_only_projection`
- [ ] A `governance` map node appears in `MAP_SURFACES` as a read-only index node; it is inert (not routable) unless the `receipts` occupant is available; when available it routes via `receipts.open`.
  - Verify: `tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state`
- [ ] Neither the governance grid nor a zero-count governance row renders on `cold_start`.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] The governance counts row carries no mutation affordance (no confirm/reject/execute button).
  - Verify: `tests/companion_ui/test_receipts_history_surface.py::test_governance_counts_render_as_read_only_projection`

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_receipts_history_surface.py::test_governance_counts_render_as_read_only_projection \
  tests/companion_ui/test_system_map_overlay.py::test_relocated_map_counts_are_read_only_projection_without_zero_state \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions
```

## Out of Scope

- Interactive governance actions (those remain on the Panel rail / `governance.queue` intent owned by the workspace contract).
- Receipt creation or modification (receipts surface is read-only per #1794).
- Governance actions in the map (the map is a projection index, not an action surface).

## Restart / Durability Posture

Governance counts are runtime-read projections from the orientation payload. Nothing survives a process restart beyond what the payload re-supplies. An empty governance object on the next orientation correctly suppresses the count row — the operator sees no manufactured "0 proposals" placeholder.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- `companion-ui/companion-app/companion_ui/workspace/receipts_history.py`
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py`
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_render_orientation_governance`)

## Related GitHub Issues

Parent: #2174. One implementation issue; can parallelize with REENTRY_COUNTS_ORIENTING_CARD. No prerequisite on Task 1.
