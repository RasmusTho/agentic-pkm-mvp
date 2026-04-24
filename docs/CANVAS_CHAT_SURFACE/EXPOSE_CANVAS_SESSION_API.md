---
name: Expose Canvas Session API
description: Add a bounded API surface for canvas session lifecycle (open, edit, close) so the canvas Chat surface can be driven from outside the process — CLI, API client, or future UI — without committing to an editor library or hosting location.
task_id: CANVAS-04
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md :: What This Spec Does Not Do
parent_capability: Canvas Chat Surface
prerequisites: [CANVAS-01, CANVAS-02, CANVAS-03]
depends_on: [WRITE_SESSION_LOGS.md, CO_AUTHOR_NOTE_BODY.md, GATE_GOVERNANCE_BEARING_MUTATIONS.md]
can_parallelize_with: []
---

State: Specification. Not yet implemented.

# Expose Canvas Session API

## Purpose

The three prior tasks implement the canvas write path internally. This task makes it externally callable — a bounded API surface that can be driven from a CLI, a test, or a future UI without the caller needing to know about `SessionLogWriter`, `CanvasWriter`, or `GovernanceRouter` directly.

## What This Task Does

1. **FastAPI routes** under `/api/canvas/`:
   - `POST /api/canvas/sessions` — open a session on a note; returns `session_id` and `note_path`
   - `POST /api/canvas/sessions/{session_id}/edits` — apply a body edit; body: `{ "new_body": "...", "change_summary": "..." }`; returns updated note content
   - `POST /api/canvas/sessions/{session_id}/governance` — request a governance action; body: `{ "action_type": "...", "payload": {...} }`; returns `pending_intent_id`
   - `DELETE /api/canvas/sessions/{session_id}` — close the session; body: `{ "total_summary": "..." }`; returns session log path

2. **CLI commands** (follow existing `python -m app.cli` conventions):
   - `python -m app.cli canvas open <note-path> [--label <label>]`
   - `python -m app.cli canvas edit <session-id> --body <body> [--summary <summary>]`
   - `python -m app.cli canvas close <session-id> [--summary <summary>]`

3. **Session store** — in-memory session registry (keyed by `session_id`) for the process lifetime. Sessions are not persisted to DB; the session log on disk is the durable artifact. If the process restarts, open sessions are lost (acceptable — session durability is a later concern).

4. **Auth** — canvas routes respect the same API key auth as existing routes (`docs/SECURITY.md`).

5. **Environment gate** — the canvas routes are available in `dev` and `test` environments; in `prod` the routes exist but return `403` if `CANVAS_ENABLED=0` (default in prod until the capability is promoted). This follows the existing feature-gate pattern.

## Concretely

```bash
# CLI: open a session
python -m app.cli canvas open vault/notes/my-note.md --label "expand-context"
# → Session opened: session_id=<uuid>, note=vault/notes/my-note.md

# CLI: apply an edit
python -m app.cli canvas edit <uuid> --body "## Context\n\nExpanded..." --summary "Expanded context section"
# → Edit applied. Note updated.

# CLI: close the session
python -m app.cli canvas close <uuid> --summary "Added context section, one governance action pending"
# → Session closed. Log at vault/.chats/my-note/2026-04-22T14-30-expand-context.md
```

```bash
# API: open, edit, close
curl -X POST /api/canvas/sessions \
  -d '{"note_path": "vault/notes/my-note.md", "session_label": "expand-context"}'
# → {"session_id": "<uuid>", "note_path": "vault/notes/my-note.md"}

curl -X POST /api/canvas/sessions/<uuid>/edits \
  -d '{"new_body": "Expanded body...", "change_summary": "Expanded context section"}'
# → {"ok": true, "note_path": "..."}

curl -X DELETE /api/canvas/sessions/<uuid> \
  -d '{"total_summary": "One edit applied"}'
# → {"ok": true, "session_log_path": "vault/.chats/my-note/..."}
```

## Why This Matters

Without this surface, the canvas write path is only usable in tests and internal code. The API and CLI are what make it possible to drive canvas sessions from an LLM agent, a future Obsidian plugin, or a web client — without any of those callers needing to change when the internal writer implementation evolves. The `CANVAS_ENABLED` gate also keeps prod conservative: the routes exist but stay off until the capability is promoted as supported.

## Acceptance Criteria

- [ ] `POST /api/canvas/sessions` opens a session and returns `session_id`.
  - Verify: `tests/api/test_canvas_api.py::test_open_session_returns_session_id`
- [ ] `POST /api/canvas/sessions/{id}/edits` applies a body edit and the vault file is updated.
  - Verify: `tests/api/test_canvas_api.py::test_edit_updates_vault_file`
- [ ] `DELETE /api/canvas/sessions/{id}` closes the session and the session log is on disk.
  - Verify: `tests/api/test_canvas_api.py::test_close_session_writes_log`
- [ ] Governance action route creates a Panel intent and returns `pending_intent_id`; does not mutate the note directly.
  - Verify: `tests/api/test_canvas_api.py::test_governance_action_creates_intent_not_note_edit`
- [ ] Canvas routes return `403` when `CANVAS_ENABLED=0` (default prod gate).
  - Verify: `tests/api/test_canvas_api.py::test_canvas_disabled_returns_403`
- [ ] `python -m app.cli canvas open / edit / close` round-trip works against `vault-test/`.
  - Verify: `tests/cli/test_canvas_cli.py::test_canvas_cli_open_edit_close_roundtrip`
- [ ] Existing routes and tests are not broken.
  - Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"` passes.

## How to Verify (Pre-Merge)

```bash
# Full canvas test suite
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/ tests/api/test_canvas_api.py tests/cli/test_canvas_cli.py -m "not pg" -q

# CLI smoke against vault-test
SESSION=$(python -m app.cli canvas open vault-test/notes/test-note.md --label smoke | grep session_id | awk '{print $2}')
python -m app.cli canvas edit $SESSION --body "Edited." --summary "smoke edit"
python -m app.cli canvas close $SESSION --summary "smoke done"
# Confirm vault-test/.chats/test-note/ contains the log

# Regression: existing smoke commands still pass
python -m app.cli health --json
python -m app.cli status
```

## Out of Scope

- Streaming edits over WebSocket (deferred to editor layer).
- Persistent session storage across process restarts.
- UI or editor library integration.
- Workspace mode (multi-note sessions).
- Hybrid Panel/Chat integration.

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/CO_AUTHOR_NOTE_BODY.md` — co-authoring path this routes to
- `docs/CANVAS_CHAT_SURFACE/GATE_GOVERNANCE_BEARING_MUTATIONS.md` — governance path this routes to
- `docs/SECURITY.md` — API key auth
- `docs/OPERATIONS.md` — environment posture and feature gates

## Related GitHub Issues

When filed, the issue should reference "Implements CANVAS_CHAT_SURFACE/EXPOSE_CANVAS_SESSION_API" and must not add streaming, persistent sessions, or UI to its scope.
