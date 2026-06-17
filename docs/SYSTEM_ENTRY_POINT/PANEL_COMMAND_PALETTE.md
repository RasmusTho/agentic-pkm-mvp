---
name: Panel Command Palette
description: ⌘K command-palette presentation of existing Panel proposals, including blocked and receipt flows, reusing POST /api/panel/confirm
task_id: SEP-04
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Surface composition (NORMATIVE table)
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [SYSTEM_MAP_OVERLAY.md, SETTINGS_DRAWER.md, RECEIPTS_HISTORY_SURFACE.md, GUIDANCE_LAYER.md]
---

# Panel Command Palette

## Purpose

Give the keyboard-first expert a fast presentation of the existing Panel governed-action lane. The palette is a **presentation of Panel, not new authority**: same proposals, same confirm endpoint, same receipts.

## What This Task Does

- Mounts a command palette on the overlay host, opened by `⌘K` / `cmd.open`.
- Renders the **existing** Panel proposals (same server-declared proposal objects as the rail, keyed by `data-proposal-id`), each tagged with its server-declared class; confirm routes through the existing `POST /api/panel/confirm` flow; receipts surface exactly as the rail surfaces them.
- Renders the **blocked flow**: a WriteGuard-denied proposal presents as a calm guard-held state per `BLOCKED_AND_STALE_STATE_SPEC.md` (gate, reason, intent preserved), never a generic error.
- Is **visually and behaviorally distinct from chat**: a callout states Panel ≠ Chat; no conversational composer; no free-text generation. The palette input filters/selects among declared proposals and commands (exact input grammar is deferred — package Q12 — a filter input is sufficient for this slice).
- The same proposal object shows identical status and actions in the rail and in the palette (overlay-grammar continuity rule).

## Concretely

```text
⌘K → palette over the anchor; proposals listed with authority tags
confirm → "Executing via governed path…" → receipt (same receipt as rail)
confirm cross-note proposal outside allowlist → calm blocked state with gate + reason
Esc → anchor, rail state unchanged
```

## Why This Matters

If the palette grew its own confirm path or proposal source it would become a fourth authority surface — the exact thing the composition forbids. Reuse keeps "Panel owns governed action" true while making it reachable without the pointer.

## Acceptance Criteria

- [ ] The palette renders the same server-declared proposal set as the Panel rail with identical `data-proposal-id`s, status, and actions.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_palette_renders_same_proposals_as_rail`
- [ ] Confirm from the palette routes through `POST /api/panel/confirm` and surfaces the runtime receipt; no palette-local execution or receipt invention.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_palette_confirm_routes_through_panel_confirm`
- [ ] A guard-denied proposal renders the calm blocked state with gate and reason, distinct from a generic error.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_blocked_proposal_renders_guard_held_state`
- [ ] The palette contains no chat composer and renders the Panel ≠ Chat distinction.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_palette_is_not_a_chat_surface`
- [ ] Proposal identity is never inferred from rendered position.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_proposal_identity_from_id_not_position`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_panel_command_palette.py`
- `pytest -q tests/companion_ui/test_governance_queue_browser.py tests/companion_ui/test_act_mode_browser.py`
- `ruff check app tests`

## Out of Scope

- New Panel actions, action classes, or confirm semantics.
- A command grammar (free text / slash commands / fuzzy match) beyond simple filtering — package Q12.
- Replacing or relocating the Panel rail.
- Any chat behavior.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Intent vocabulary, §Authority boundaries
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md`
- `companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md`

## Related GitHub Issues

Filed as **#1786** (`[SystemEntryPoint] panel-command-palette: ⌘K presentation of Panel proposals`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
