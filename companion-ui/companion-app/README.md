# Companion App Staging

This folder contains implementation staging artifacts and production-candidate Canvas Core modules for the companion UI.

## Canvas Core implementation modules (production-candidate)

Canvas Core production-candidate Python modules live in the `companion_ui/` package:

```
companion-ui/companion-app/
└── companion_ui/                         ← importable Python package root
    └── canvas_core/
        ├── __init__.py
        ├── session_state.py              ← Canvas session lifecycle state machine
        └── active_artifact_shell.py      ← Active artifact body shell contract
```

The `companion-ui/companion-app/` directory is the package root added to `sys.path` by `tests/companion_ui/conftest.py`.  Import in tests as:

```python
from companion_ui.canvas_core.session_state import CanvasSessionState
from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
```

- `session_state.py` — Canvas session lifecycle state machine (`start → active → paused/interrupted → closed`).  Enforces body-edit authority: direct edits are allowed only when the session is `active` and user-present.  This is **not** Canvas bounded suggestion flow state.
- `active_artifact_shell.py` — Active artifact body shell contract.  Declares the four canonical Canvas layout regions (`canvas-artifact-body`, `canvas-session-controls`, `canvas-provenance`, `canvas-escape-hatch`) and asserts the artifact body as the primary surface.  Portrait/mobile layouts must preserve the artifact body as the cognitive anchor.

Canvas Core tests live in `tests/companion_ui/`:
- `test_canvas_session_lifecycle.py` — verifies lifecycle state machine (#1024)
- `test_canvas_active_artifact_shell.py` — verifies active artifact body shell (#1025)

## Staging prototypes (non-production)

The following files are **staging/prototype artifacts** and remain non-production until explicitly promoted:

- `converse_layout.html` / `.css` / `_state.py` — original converse layout shell.
- `canvas_suggestion_flow.html` / `.css` — **Canvas Suggestion Flow staging prototype** (2026-05-11). Implements the 8-state UI model from the design spec at `design_handoff/2026-05-11-canvas-suggestion-flow/`. Open in a browser; use the lane-switcher tabs to walk the body-edit, governance, blocked, and idle states.  **This is bounded-suggestion staging only — it is not Canvas Core.**
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
