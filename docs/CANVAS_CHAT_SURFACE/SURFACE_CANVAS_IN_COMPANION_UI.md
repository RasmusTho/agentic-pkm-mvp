---
name: Surface Canvas In Companion UI
description: Make agentic canvas co-authoring reachable in the Companion UI dev/staging shell — an intent input, applied-edit rendering, undo, and session open/close wired to the canvas endpoints
task_id: AGENTIC-CANVAS-02
source_anchor: docs/CANVAS_CHAT_SURFACE/GENERATE_COAUTHORING_EDIT.md :: What This Task Does
parent_capability: Agentic Canvas Co-Authoring
prerequisites: [AGENTIC-CANVAS-01]
depends_on:
  - GENERATE_COAUTHORING_EDIT.md
can_parallelize_with: []
---

State: Implementation task specification. The Companion UI shell renders a read-only workspace, a body-edit composer, and the Panel rail, but has no canvas co-authoring surface; `workspace_http_client.py` only knows session open/close and panel confirm, not `/coauthor`, `/edits`, or undo. This task makes the agentic canvas loop reachable in the shell.
Doc role: Implementation task spec
Authority: Renders the co-authoring surface defined by `GENERATE_COAUTHORING_EDIT.md`. Server declares; UI renders. Does not introduce UI-local authority.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-08

# Surface Canvas In Companion UI

## Purpose

The backend can now co-author (`AGENTIC-CANVAS-01`), but a user cannot reach it from the Companion UI. The shell (`companion-ui/companion-app/companion_ui/workspace/real_note_workspace_shell.py`) has no intent input and no live-edit region, and the HTTP client (`workspace/workspace_http_client.py`) lacks the co-author and undo calls. This task wires the surface so "open a note, state an intent, watch the agent edit in place, undo if needed" works end to end in dev/staging.

## What This Task Does

- Extend `workspace_http_client.py` with `coauthor(session_id, intent, change_summary=None)` → `POST /api/canvas/sessions/{id}/coauthor` and `undo_last_edit(session_id)` → `DELETE /api/canvas/sessions/{id}/edits/last`. Session open/close already exist.
- Add a canvas co-authoring region to the workspace shell: an intent input, a render of the applied edit (the updated body, with the change summary the server returned), and an undo affordance. The region is shown only when the server-declared `guards.canvas_enabled` is true; when disabled it renders an inert disabled state, never a local mutation affordance.
- The session lifecycle is explicit: opening the canvas region opens a session (existing `POST /api/canvas/sessions`); leaving closes it (existing `DELETE /api/canvas/sessions/{id}`).
- The UI never composes the new body itself and never writes to the vault directly — it sends the intent and renders the server's applied result. Governance-bearing responses from the server are shown as routed-to-Panel, not as an applied edit.

## Concretely

```
Companion UI dev shell, note open, CANVAS_ENABLED=1:
  [ intent: "tighten the intro paragraph" ]  (Co-author)
  -> POST /api/canvas/sessions/{id}/coauthor
  -> body region re-renders with the applied edit + "tightened intro paragraph"
  -> (Undo) -> DELETE /api/canvas/sessions/{id}/edits/last -> prior body restored

CANVAS_ENABLED unset:
  -> canvas region renders disabled; no intent input, no Co-author button
```

## Why This Matters

This is the task that makes the capability demonstrable. Without it the agent exists but is invisible, and the Companion UI keeps looking like a read-only viewer with a Panel rail — indistinguishable in purpose from Obsidian. The co-authoring surface is the differentiator the product is built around.

## Acceptance Criteria

- [ ] The HTTP client exposes a co-author call that posts intent to `/api/canvas/sessions/{id}/coauthor`.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_http_client_coauthor_posts_intent`
- [ ] The HTTP client exposes an undo call that deletes the last edit.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_http_client_undo_deletes_last_edit`
- [ ] The shell renders an intent input and applied-edit region when `canvas_enabled` is true.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_shell_renders_canvas_region_when_enabled`
- [ ] When `canvas_enabled` is false the shell renders an inert disabled state with no mutation affordance.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_shell_canvas_region_disabled_when_flag_off`
- [ ] A governance-bearing server response is rendered as routed-to-Panel, not as an applied edit.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_governance_bearing_response_shown_as_panel_routed`
- [ ] The UI performs no direct vault write and composes no body locally; only server-applied bodies render.
  Verify: `tests/companion_ui/test_canvas_coauthoring_surface.py::test_no_local_vault_write_or_body_composition`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_canvas_coauthoring_surface.py`
- `ruff check app tests companion-ui`
- `git diff --check`
- Manual (dev shell, `CANVAS_ENABLED=1`): open a note, enter an intent, confirm the body re-renders with the applied edit and undo restores the prior body. Confirm the region is disabled when the flag is unset.

## Out of Scope

- Token-level streaming of the edit (returns applied body).
- Production packaging/hardening of the Companion UI.
- Chat→Panel governance handoff UX beyond showing routed-to-Panel state (future hybrid slice).
- Resurface/Act surface changes.
- Any change to the canvas backend authority model (owned by `AGENTIC-CANVAS-01`).

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/README.md`
- `docs/CANVAS_CHAT_SURFACE/GENERATE_COAUTHORING_EDIT.md`
- `companion-ui/docs/MLP_CAPABILITY_MATRIX.md` (Canvas rows)
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md` (Act / Canvas surfaces)
- `companion-ui/companion-app/companion_ui/workspace/real_note_workspace_shell.py`, `workspace/workspace_http_client.py`

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/SURFACE_CANVAS_IN_COMPANION_UI" and must preserve server-declares/UI-renders and the `canvas_enabled` gate.
