---
name: Surface Chat To Panel Handoff
description: In the Companion UI, link the canvas co-authoring region's panel-routed state to the actual staged Panel proposal (by intent_id) and show that proposal in the Panel rail as canvas-originated, so the user can decide/confirm it through the existing Panel flow
task_id: CHAT-PANEL-HANDOFF-02
source_anchor: docs/CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE.md :: What This Task Does
parent_capability: Chat to Panel Governance Handoff
prerequisites: [CHAT-PANEL-HANDOFF-01]
depends_on:
  - RETURN_GOVERNANCE_HANDOFF_REFERENCE.md
  - SURFACE_CANVAS_IN_COMPANION_UI.md
can_parallelize_with: []
---

State: Implementation task specification. After CHAT-PANEL-HANDOFF-01 the API returns a handoff reference, but the Companion UI still only renders a generic `is_panel_routed` flag on the canvas region with no link to the proposal. This task connects the two surfaces visually.
Doc role: Implementation task spec
Authority: Renders the "Panel command locality" side of the crossing. Server declares, UI renders. Panel remains the primary command surface; Chat does not inherit Panel's authority.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-09

# Surface Chat To Panel Handoff

## Purpose

A user co-authoring a note states a governance-bearing intent ("promote to evergreen"). The runtime routes it to a Panel proposal. Today the Companion UI shows only "routed to Panel" with no way to find or act on it. This task makes the handoff navigable: the canvas region links to the staged proposal, and the Panel rail shows it as canvas-originated, so the user completes it through the existing Panel decide/confirm flow.

## What This Task Does

- Extend the canvas co-authoring region (`CanvasCoAuthorRegion` in `real_note_workspace_shell.py`) so its panel-routed state carries the handoff reference (`intent_id`, `action_type`) returned by CHAT-PANEL-HANDOFF-01, plus a "view in Panel" affordance keyed to that `intent_id`.
- In the Panel rail rendering (`real_note_workspace_dev_page.py` proposal rows), surface the the proposal-scoped `origin="canvas_coauthoring"` (the dedicated proposal field from CHAT-PANEL-HANDOFF-01, not the vault-note/frontmatter `origin`) attribution on the matching proposal so the user sees it came from their canvas intent.
- Reuse the existing confirm path (`confirm_panel_proposal` / `POST /api/panel/confirm`); this task adds correlation and attribution, not a new execution path.
- Server declares, UI renders: the UI correlates by the server-provided `intent_id`/`origin`; it must not synthesize proposals, infer governance, or execute locally.

## Concretely

```
Canvas region (governance-bearing intent):
  "Routed to Panel — maturity_transition  [view in Panel →]"   (intent-abc123)

Panel rail:
  ▸ Proposal: promote to evergreen   origin: canvas co-authoring
    [decide] → [confirm] → receipt        (existing flow)
```

## Why This Matters

This is the visible half of the hybrid handoff. Without it the authority split exists only server-side and the user experiences a dead end. With it, the user sees one coherent story: my co-authoring intent was governance-bearing, so it became a governed Panel proposal I can decide on — exactly the Panel/Chat distinction the schema protects.

## Acceptance Criteria

- [ ] The canvas region's panel-routed state stores the handoff `intent_id` and `action_type` from the server response.
  Verify: `tests/companion_ui/test_chat_to_panel_handoff.py::test_region_stores_handoff_reference`
- [ ] The canvas region exposes a "view in Panel" affordance only when a handoff reference is present.
  Verify: `tests/companion_ui/test_chat_to_panel_handoff.py::test_region_view_in_panel_affordance_present_with_reference`
- [ ] The Panel rail renders the matching proposal with its server-declared the proposal-scoped `origin="canvas_coauthoring"` (the dedicated proposal field from CHAT-PANEL-HANDOFF-01, not the vault-note/frontmatter `origin`) attribution.
  Verify: `tests/companion_ui/test_chat_to_panel_handoff.py::test_panel_rail_shows_canvas_origin`
- [ ] Confirmation routes through the existing `POST /api/panel/confirm` path; no new execution path is introduced.
  Verify: `tests/companion_ui/test_chat_to_panel_handoff.py::test_confirm_uses_existing_panel_path`
- [ ] The UI synthesizes no proposal and infers no governance locally (correlation is by server-provided fields).
  Verify: `tests/companion_ui/test_chat_to_panel_handoff.py::test_no_local_proposal_synthesis`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_chat_to_panel_handoff.py`
- Regression: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui` (state any pre-existing unrelated failures explicitly).
- `ruff check app tests companion-ui`
- `git diff --check`

## Out of Scope

- Receipt reflection back into the canvas context (that is `REFLECT_HANDOFF_RECEIPT.md`).
- Backend handoff reference shape (owned by CHAT-PANEL-HANDOFF-01).
- Changes to the Panel admission/confirm/execute pipeline.
- Hosting/packaging decisions.

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`
- `companion-ui/companion-app/companion_ui/workspace/real_note_workspace_shell.py`, `real_note_workspace_dev_page.py`

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/SURFACE_CHAT_TO_PANEL_HANDOFF" and must preserve server-declares/UI-renders and Panel-as-primary-command-surface.
