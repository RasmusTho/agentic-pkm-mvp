---
name: Write Session Logs
description: Implement the session log writer and the chat-session artifact class — the subordinate provenance trail captured alongside the note during a canvas session.
task_id: CANVAS-01
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md :: Artifact Classes
parent_capability: Canvas Chat Surface
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Implemented. Delivered by PR #687 (issue #683, 2026-04-29).

# Write Session Logs

## Purpose

Every canvas session produces a session log: an append-only provenance artifact that captures what the user intended and what changed. This task creates the writer and the artifact class that all downstream canvas tasks depend on.

## What This Task Does

Implements the session log writer:

1. **Artifact location** — `vault/.chats/<note-slug>/<timestamp>-<short-label>.md` where:
   - `<note-slug>` is the note's filename without extension, lowercased and hyphenated
   - `<timestamp>` is ISO-8601 with colons replaced by hyphens (`2026-04-22T14-30`)
   - `<short-label>` is a max-5-word human description of the session intent, hyphenated (e.g. `restructure-decision-section`)

2. **Frontmatter** — every session log carries:
   ```yaml
   ---
   type: chat-session
   note: "[[<note-title>]]"
   date: <ISO-8601 timestamp>
   session_id: <uuid4>
   ---
   ```

3. **Append-only during session** — the session log is opened at session start and appended to as the session progresses. It is not rewritten. Appends record: user prompt, brief change summary (not full LLM response body).

4. **Closed at session end** — a final append records the session-close event with a summary of total changes.

5. **Writer module** — `app/chat/session_log.py` (new), with `SessionLogWriter` class:
   - `open_session(note_path, session_label) -> SessionLog`
   - `append_turn(session, user_prompt, change_summary)`
   - `close_session(session, total_summary)`

6. **No retention enforcement** — this task only writes logs. Retention policy (soft-delete after window) is a later slice.

## Concretely

```python
from app.chat.session_log import SessionLogWriter

writer = SessionLogWriter(vault_root=Path("vault"))
session = writer.open_session(
    note_path=Path("vault/notes/my-design-decision.md"),
    session_label="restructure-decision-section"
)
writer.append_turn(
    session,
    user_prompt="Can you move the rationale into a dedicated subsection?",
    change_summary="Moved three paragraphs under new ## Rationale heading"
)
writer.close_session(session, total_summary="One structural edit: rationale section added")
```

Expected output file at `vault/.chats/my-design-decision/2026-04-22T14-30-restructure-decision-section.md`:
```markdown
---
type: chat-session
note: "[[my-design-decision]]"
date: 2026-04-22T14:30
session_id: <uuid>
---

## Session: restructure-decision-section

**User:** Can you move the rationale into a dedicated subsection?
**Change:** Moved three paragraphs under new ## Rationale heading

---
*Session closed. Total: One structural edit: rationale section added.*
```

## Why This Matters

The session log is the provenance contract. Without it, co-authored notes have no intent trail — the user cannot later ask "why did this section appear?" and get a useful answer. The `.chats/` namespace and `type: chat-session` field also ensure session logs are distinguishable from vault notes in Dataview, graph view, and system retrieval, so they never pollute the human writing surface.

## Acceptance Criteria

- [ ] `app/chat/session_log.py` exists with `SessionLogWriter`, `open_session`, `append_turn`, and `close_session`.
  - Verify: `tests/chat/test_session_log_writer.py::test_open_creates_file_in_chats_namespace`
- [ ] Session log files are created under `vault/.chats/<note-slug>/` with correct path structure.
  - Verify: `tests/chat/test_session_log_writer.py::test_log_path_uses_note_slug_and_timestamp`
- [ ] Session log frontmatter contains `type: chat-session`, `note`, `date`, and `session_id` fields.
  - Verify: `tests/chat/test_session_log_writer.py::test_frontmatter_fields_present`
- [ ] `type: chat-session` is not present in any existing vault note class (no collision with user artifacts).
  - Verify: `tests/chat/test_session_log_writer.py::test_type_field_is_chat_session_only`
- [ ] Appends are additive; prior content is not rewritten.
  - Verify: `tests/chat/test_session_log_writer.py::test_append_does_not_rewrite_prior_content`
- [ ] `close_session` records a final closure line with the total summary.
  - Verify: `tests/chat/test_session_log_writer.py::test_close_session_appends_closure_line`
- [ ] The writer does not require Docker or Postgres (pure file-system operation).
  - Verify: `pytest tests/chat/test_session_log_writer.py -m "not pg" -q` passes.

## How to Verify (Pre-Merge)

```bash
# Unit tests — no PG, no Docker
pytest tests/chat/test_session_log_writer.py -m "not pg" -q

# Smoke: create a session log manually
python -c "
from pathlib import Path
from app.chat.session_log import SessionLogWriter
w = SessionLogWriter(vault_root=Path('vault-test'))
s = w.open_session(Path('vault-test/notes/test-note.md'), 'smoke-test-session')
w.append_turn(s, 'test prompt', 'test change')
w.close_session(s, 'smoke complete')
print('Log at:', s.log_path)
"
# Confirm: vault-test/.chats/test-note/ contains the log file with correct frontmatter
```

## Out of Scope

- Retention policy enforcement (soft-delete window).
- Session log retrieval or search.
- Rendering session logs in any UI.
- Integration with the co-authoring write path (that is CO_AUTHOR_NOTE_BODY).
- The full session schema beyond the minimum fields listed above.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` §Artifact Classes, §File-System Conventions, §Retention and Reversibility
- `docs/CANVAS_CHAT_SURFACE/README.md`

## Related GitHub Issues

When filed, the issue should reference "Implements CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS" and must not add retention policy enforcement to its scope.
