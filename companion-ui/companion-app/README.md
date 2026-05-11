# Companion App Staging

This folder contains implementation staging artifacts for the companion UI.

Current contents are prototype/reference shell files for converse layout behavior and should be treated as non-production until explicitly promoted.

Files:
- `converse_layout.html` / `.css` / `_state.py` — original converse layout shell.
- `canvas_suggestion_flow.html` / `.css` — **Canvas Suggestion Flow staging prototype** (2026-05-11). Implements the 8-state UI model from the design spec at `design_handoff/2026-05-11-canvas-suggestion-flow/`. Open in a browser; use the lane-switcher tabs to walk the body-edit, governance, blocked, and idle states.
- `colors_and_type.css` — Yggdrasil design token sheet (shared with design_handoff).

## Prototype scope (canvas_suggestion_flow.html)

This file is a **staging prototype** — not production runtime:

- **No network side effects.** No real API calls are made.
- **No durable mutations.** No data is written to the vault, database, or any external system.
- **Console/demo calls only.** Backend interactions are simulated via `console.log` entries (e.g., `[canvas_writer.apply_edit]`, `[GovernanceRouter.request_governance_action]`, `[session-log:append_turn]`).
- **Not production runtime.** The lane-switcher tab bar, hardcoded session paths, and simulated turn delays are demo scaffolding absent from any production implementation.
- **Non-production until explicitly promoted.** No file in this folder becomes production code until a formal promotion decision is recorded in a PR.

See `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` for the normalized implementation spec and `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/` for the design handoff archive.

## General boundaries
- No production backend integrations in this workspace phase.
- Keep overlay-first, document-first interaction behavior intact.
- Keep runtime state ephemeral unless an explicit persistence contract is introduced.
