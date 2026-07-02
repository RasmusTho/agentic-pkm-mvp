---
name: Persist Chat Artifact Through WriteGuard
description: Route chat-session artifact writes through WriteGuard + KnowledgePort (mirroring commitment_persistence.py) and add the durable note_uuid relationship field, closing D-4's restart-durability and note-relationship gaps for real
task_id: CANVAS-DURABLE-02
source_anchor: docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md :: Chat-Session Artifact Classification
parent_capability: Canvas Chat Surface (Phase 5)
prerequisites: [CANVAS-DURABLE-01]
depends_on:
  - DEFINE_CHAT_ARTIFACT_DURABILITY.md
can_parallelize_with: []
---

State: Specification for the durable chat-artifact write path. Slice 2 of Phase 5. Code-affecting.

# Persist Chat Artifact Through WriteGuard

## Purpose

`app/chat/session_log.py`'s `SessionLogWriter` writes chat-session files with raw
`Path.write_text`/`open(...).write(...)` calls — no `WriteGuard.assert_writes_allowed(...)` call
anywhere in the module, and no `KnowledgePort`/`write_note_relative` routing. Every other durable HKA
artifact in this system (companion notes, commitment artifacts, materialized memory) goes through
WriteGuard before touching disk. Chat-session artifacts are the one exception, and per
`docs/SYSTEM_BREAKDOWN_STRUCTURE.md` Part 4's forbidden-dependency table, an interaction surface
writing directly into HKA-owned durable storage without going through the owning write seam is exactly
the pattern the boundary rules exist to prevent. This task closes that gap and adds the durable
`note_uuid` field defined in `DEFINE_CHAT_ARTIFACT_DURABILITY.md`.

## What This Task Does

- Adds `note_uuid: str` to `SessionLog` (currently `log_path`, `session_id`, `note_path`, `label`,
  `vault_root`), resolved via `app.services.note_uuid.ensure_note_uuid(note_path, vault_root=...)` at
  `open_session(...)` time — the same healing/read call every other identity-anchored artifact in this
  system uses, so a note without a UUID yet gets one healed rather than the session silently omitting
  the field.
- Writes `note_uuid: <uuid>` into the chat-session frontmatter alongside the existing `note:
  "[[title]]"` field (both present — human-legible link kept, durable anchor added). No other
  frontmatter field from `DEFINE_CANVAS_COEDITING_MODEL.md`'s minimum set (`type`, `note`, `date`,
  `session_id`) changes shape or meaning.
- Asserts `DEFAULT_WRITE_GUARD.assert_writes_allowed("chat_session.persist")` before every filesystem
  mutation in `SessionLogWriter`: `open_session` (create), `append_turn` (append), `close_session`
  (terminal write) — mirroring `app/services/commitment_persistence.py:137` (WriteGuard first, nothing
  on disk when blocked) and `app/agent_memory/materialization.py`'s write pattern. A blocked write
  raises `WritesBlockedError` and leaves the artifact exactly as it was before the call (no partial
  turn, no half-created session file).
- Routes the actual file mutation through `app.knowledge.write_ops.write_note_relative` /
  `append_note_relative` (KnowledgePort) instead of raw `Path`/`open()` calls, so chat-session writes
  go through the same HKA-owned write seam as companion notes and commitments — curing the
  forbidden-dependency instance named in `DEFINE_CHAT_ARTIFACT_DURABILITY.md`'s SBS Classification
  section.
- Adds a query function, `load_chat_sessions_for_note(note_uuid, *, vault_context) -> list[SessionLog]`,
  reading `note_uuid` from frontmatter across `.chats/**/*.md` (glob + frontmatter parse, mirroring
  `commitment_persistence.load_commitments`) — the read-side completion of "a note may have several
  chats attached to it," independent of directory-slug grouping so a stale slug (post-rename) does not
  hide a session from this query.

## Concretely

```python
# Open a session — WriteGuard asserted, note_uuid resolved and written:
writer = SessionLogWriter(vault_root=vault_root)
session = writer.open_session(note_path, "restructure")
assert session.note_uuid == ensure_note_uuid(note_path, vault_root=vault_root)

# Frontmatter now carries both the human link and the durable anchor:
# ---
# type: chat-session
# note: "[[v6-architecture]]"
# note_uuid: 3f1e2a...
# date: 2026-07-02T14:30
# session_id: <uuid>
# ---

writer.append_turn(session, "clean up the intro", "reworded first two paragraphs")
writer.close_session(session, "restructured intro and decision section")

# ... process restart, note later renamed (directory slug now stale) ...

sessions = load_chat_sessions_for_note(session.note_uuid, vault_context=ctx)
assert any(s.session_id == session.session_id for s in sessions)  # found via note_uuid, not slug

# Write-blocked runtime state:
# writer.append_turn(...) raises WritesBlockedError; the file on disk is unchanged from
# before the call (no partial turn appended).
```

## Why This Matters

Two concrete failures exist today and this task closes both:

1. **No restart-safe relationship.** The only note↔session link today is a directory-slug
   (`.chats/<note-slug>/`) and a title-string wikilink in frontmatter. Neither survives a note rename
   cleanly (the slug directory does not move; the wikilink title string is not guaranteed to be
   rewritten by Obsidian for a dotfile-hidden system path). `load_chat_sessions_for_note` and the
   `note_uuid` field make the relationship rename-safe, the same guarantee every other identity-bearing
   artifact in this system already has.
2. **No WriteGuard gate.** A degraded runtime state (the same state that blocks every other durable
   write) currently does nothing to stop chat-session writes — they are the one silent exception.
   Beyond consistency, this is the concrete mechanism the SBS forbidden-dependency rule requires: an
   interaction surface (Canvas/HIX) must not write HKA-owned durable storage directly.

## Acceptance Criteria

- [ ] `SessionLog` carries a `note_uuid` field, resolved via `ensure_note_uuid` at session-open time,
      and written into the chat-session frontmatter alongside the existing `note:` field.
      Verify: `tests/chat/test_session_log_writer.py::test_open_session_resolves_and_writes_note_uuid`
- [ ] Every `SessionLogWriter` write path (`open_session`, `append_turn`, `close_session`) asserts
      `DEFAULT_WRITE_GUARD.assert_writes_allowed("chat_session.persist")` at the production call site
      before any filesystem mutation; a write-blocked runtime state raises `WritesBlockedError` and
      leaves the artifact unchanged (enforcement asserted at the call site, not the guard in
      isolation, per `ISSUE_CONTRACT.md`'s enforcement-AC rule).
      Verify: `tests/chat/test_session_log_writer.py::test_writes_blocked_by_writeguard_at_call_site`
      — patches the runtime state to a write-blocked state and asserts each of the three production
      methods raises and mutates nothing.
- [ ] Chat-session file mutations route through `write_note_relative`/`append_note_relative`
      (KnowledgePort), not raw `Path`/`open()` calls.
      Verify: `tests/chat/test_session_log_writer.py::test_writes_route_through_knowledge_port` —
      asserts the production write path calls into `app.knowledge.write_ops`, e.g. via a patch/spy on
      `write_note_relative`.
- [ ] `load_chat_sessions_for_note(note_uuid, ...)` returns all sessions for a note by `note_uuid`,
      including sessions whose on-disk directory slug is stale relative to the note's current title
      (simulated rename).
      Verify: `tests/chat/test_session_log_writer.py::test_load_by_note_uuid_survives_stale_slug`
- [ ] No existing Phase 1–4 canvas behavior regresses: the co-authoring path, governance-bearing
      routing, and the session API surface are unaffected by this change.
      Verify: `pytest -q tests/chat tests/companion_ui/test_canvas_*.py tests/api/test_canvas*.py`

## How to Verify (Pre-Merge)

- `pytest -q tests/chat/test_session_log_writer.py` — runs the four assertions above.
- `pytest -q tests/chat tests/companion_ui/test_canvas_*.py tests/api/test_canvas*.py` — full canvas
  regression sweep (shared/hot-path surface per `AGENTS.md :: Sub-agent full-suite on hot-path`
  posture — session_log.py is consumed by the API, CLI, and Companion UI canvas surfaces).
- `ruff check app tests` and `mypy app` (code-affecting change).
- Read the new write path side-by-side with `app/services/commitment_persistence.py` to confirm the
  WriteGuard-before-single-write pattern matches exactly.

## Out of Scope

- RelationIndex / `store_objects` registration (see `DEFINE_CHAT_ARTIFACT_DURABILITY.md :: Out of
  Scope` — frontmatter-only, glob-read, following the commitment precedent).
- Cold-storage/tiering implementation (D-6 mechanism not yet designed system-wide).
- Changing `.canvas-sessions/` JSON pointer-store behavior (`app/chat/session_store.py`) — that stays
  local cache, untouched by this task.
- Changing the co-authoring posture, authority split, or governance-bearing routing from Phases 1–4.
- Backfilling `note_uuid` onto chat-session files written before this task ships. Pre-existing
  `.chats/*.md` files without `note_uuid` remain readable (the field is additive going forward);
  `load_chat_sessions_for_note` simply will not find them by `note_uuid` until a separate,
  explicitly-scoped backfill task addresses historical files, if ever needed.

## Restart / Durability Posture

- **Survives restart:** the chat-session `.md` files under `vault/.chats/**`, including the new
  `note_uuid` field, exactly as before (they were already vault files) — this task adds durability
  posture (WriteGuard gating, identity) to storage that already crossed a restart, it does not newly
  cross one. The one thing this task does *not* make durable is the actual per-turn LLM response body
  — `DEFINE_CANVAS_COEDITING_MODEL.md` explicitly scopes the session log to intent + change-summary,
  "not the full LLM response body," and this task does not reopen that scope decision.
- **Does NOT survive restart (by design, unchanged):** `.canvas-sessions/*.json` (which session is
  currently "open" for CLI cross-process resume) is out of scope here and remains local-cache-only;
  losing it means the user has to re-open a session, not that any content is lost — the underlying
  `.chats/*.md` file is untouched.
- **Trust consequence if durability is not honored:** if `note_uuid` resolution silently failed and
  produced no relationship anchor, a renamed note's chat history would become undiscoverable by
  `load_chat_sessions_for_note` (though still present on disk, findable only by manual directory
  search) — a quiet loss of the very relationship D-4 was ratified to guarantee.

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md` (this phase's Task 1 — classification and reconciliation this task implements)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `app/services/commitment_persistence.py` (structural precedent)
- `app/services/note_uuid.py` (`ensure_note_uuid`)
- `app/knowledge/write_ops.py` (`write_note_relative`, `append_note_relative`)
- `app/write_guard.py`
- `app/chat/session_log.py`, `app/chat/session_store.py`

## Related GitHub Issues

Filed as #2807 (`agent:blocked` on #2806 — remove the block and add `agent:ready` once #2806 merges).
Parent feature issue: #2805.
