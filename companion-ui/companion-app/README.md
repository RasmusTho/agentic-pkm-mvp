# Companion App Staging

This folder contains implementation staging artifacts for the companion UI.

Current contents are prototype/reference shell files for converse layout behavior and should be treated as non-production until explicitly promoted.

Files:
- `converse_layout.html` / `.css` / `_state.py` — original converse layout shell.
- `canvas_suggestion_flow.html` / `.css` — Canvas Suggestion Flow staging prototype (2026-05-11). Implements the 8-state UI model from the design spec at `design_handoff/2026-05-11-canvas-suggestion-flow/`. Open in a browser; use the lane-switcher tabs to walk the body-edit, governance, blocked, and idle states.
- `colors_and_type.css` — Yggdrasil design token sheet (shared with design_handoff).

Boundaries:
- No production backend integrations in this workspace phase.
- Keep overlay-first, document-first interaction behavior intact.
- Keep runtime state ephemeral unless an explicit persistence contract is introduced.
