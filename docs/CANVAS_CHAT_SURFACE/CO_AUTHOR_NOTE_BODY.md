---
name: Co-Author Note Body
description: Implement the in-place body editing path for the currently-open note during a canvas session — authorized by user presence, written through KnowledgePort, scoped strictly to the note body.
task_id: CANVAS-02
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md :: The Canvas Co-Editing Posture
parent_capability: Canvas Chat Surface
prerequisites: [CANVAS-01]
depends_on: [WRITE_SESSION_LOGS.md]
can_parallelize_with: []
---

State: Specification. Not yet implemented.

# Co-Author Note Body

## Purpose

This task implements the core canvas posture: edits apply to the note body directly during an active session, authorized by the fact that the user opened the session. The user experiences this as co-authoring, not as reviewing diffs.

## What This Task Does

Implements the co-authoring write path:

1. **Session context** — a canvas session is open on exactly one note. The session object (from WRITE_SESSION_LOGS) carries the note path and the authorization signal.

2. **Body-scoped writer** — `app/chat/canvas_writer.py` (new) with `CanvasWriter`:
   - `apply_edit(session, new_body: str)` — replaces the note body while preserving frontmatter
   - Writes through `app/knowledge/write_ops.py` (the existing KnowledgePort boundary) so vault-write policy, idempotency, and optimistic-lock semantics apply
   - Appends a change summary to the session log via `SessionLogWriter.append_turn`

3. **Scope enforcement** — `CanvasWriter` raises `GovernanceBearingMutationError` if:
   - the caller attempts to modify frontmatter fields directly (classification, `type`, `maturity`, `review_state`, scope/sphere tags)
   - the `new_body` targets a path other than `session.note_path`
   - no session is open (no-session writes are not authorized)

4. **Frontmatter preserved** — the writer reads the current note, separates frontmatter from body, applies the edit to the body only, and reassembles. Frontmatter is never touched by the co-authoring path.

5. **Undo semantics** — because writes go to the vault file immediately, Obsidian's file watcher picks up saves normally. Undo is the user's own editor undo, not a system-level rollback mechanism.

## Concretely

```python
from pathlib import Path
from app.chat.session_log import SessionLogWriter
from app.chat.canvas_writer import CanvasWriter

log_writer = SessionLogWriter(vault_root=Path("vault"))
canvas = CanvasWriter(vault_root=Path("vault"), log_writer=log_writer)

session = log_writer.open_session(
    note_path=Path("vault/notes/my-note.md"),
    session_label="expand-context-section"
)

canvas.apply_edit(
    session=session,
    new_body="## Context\n\nExpanded rationale here...\n\n## Decision\n...",
    change_summary="Expanded Context section with three new paragraphs"
)
```

Attempting to write frontmatter via co-authoring path raises:
```python
canvas.apply_edit(session, new_body="---\nmaturity: evergreen\n---\n\nBody")
# raises GovernanceBearingMutationError: frontmatter modification is governance-bearing
```

## Why This Matters

The co-authoring path is the thing that makes canvas Chat feel like a collaborative editor rather than a chat interface. Without it, every edit is either a suggestion to approve or a mutation that bypasses the KnowledgePort boundary — both failure modes the spec names explicitly. This task ensures edits land in the vault via the same controlled boundary as all other system-originated writes, while staying strictly scoped to the note body.

## Acceptance Criteria

- [ ] `app/chat/canvas_writer.py` exists with `CanvasWriter` and `apply_edit`.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_writes_body_to_vault`
- [ ] `apply_edit` preserves existing frontmatter unchanged.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_preserves_frontmatter`
- [ ] `apply_edit` raises `GovernanceBearingMutationError` when the new body contains a frontmatter block.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_rejects_frontmatter_in_body`
- [ ] `apply_edit` raises when `session.note_path` does not match the target path.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_rejects_cross_note_target`
- [ ] `apply_edit` raises when called without an open session.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_requires_open_session`
- [ ] Every `apply_edit` call appends a change summary to the session log.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_records_turn_in_session_log`
- [ ] Writes route through `app/knowledge/write_ops.py` (KnowledgePort boundary).
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_uses_knowledge_port`
- [ ] `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/test_canvas_writer.py -m "not pg" -q` passes.

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/test_canvas_writer.py -m "not pg" -q

# Smoke: open session, apply an edit, confirm file updated, frontmatter intact
python -c "
from pathlib import Path
from app.chat.session_log import SessionLogWriter
from app.chat.canvas_writer import CanvasWriter
vr = Path('vault-test')
lw = SessionLogWriter(vault_root=vr)
cw = CanvasWriter(vault_root=vr, log_writer=lw)
note = vr / 'notes' / 'test-note.md'
note.write_text('---\ntype: note\n---\n\nOriginal body.')
s = lw.open_session(note, 'smoke-edit')
cw.apply_edit(s, 'Rewritten body.', 'body replaced')
lw.close_session(s, 'smoke done')
print(note.read_text())
# Confirm: frontmatter preserved, body = 'Rewritten body.'
"
```

## Out of Scope

- Governance-bearing mutations (frontmatter, cross-note, lifecycle) — those are GATE_GOVERNANCE_BEARING_MUTATIONS.
- Streaming edits character-by-character — the write path applies a full body replacement per call; streaming is a UI concern deferred until the editor layer is chosen.
- Multi-note sessions (workspace mode) — explicitly deferred per spec.
- Conflict resolution or merge when the note has changed externally mid-session.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` §The Canvas Co-Editing Posture, §The Authority Split :: Co-authoring
- `app/knowledge/write_ops.py` — the KnowledgePort boundary this task writes through
- `docs/CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS.md` — prerequisite

## Related GitHub Issues

When filed, the issue should reference "Implements CANVAS_CHAT_SURFACE/CO_AUTHOR_NOTE_BODY" and must not expand scope to include governance-bearing mutations or streaming.
