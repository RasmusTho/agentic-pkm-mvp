---
name: Capture to Vault Inbox
description: Governed capture endpoint (policy → validation → writer, inbox note convention) plus the ⌘N capture modal UI with session-capture list and offline honesty
task_id: SEP-08
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Resolved Q17
parent_capability: system-entry-point
prerequisites: []
depends_on: []
can_parallelize_with: [REENTRY_ORIENTATION_TREATMENT.md, UNIFIED_TOPBAR_AND_OVERLAY_HOST.md, MEMORY_REVIEW_DRAWER.md]
---

# Capture to Vault Inbox

## Purpose

Friction-free intake of "things I need to take care of" as a **commitment to future-self appended to the vault inbox** — deliberately not an app-owned task list, and never a write the UI cannot back.

## What This Task Does

This task specification maps to **two GitHub issues** (grandchildren) with a **split dependency profile** — the file-level frontmatter lists no prerequisites because they differ per issue: issue (a) has none and may start immediately after the spec merges; issue (b) requires SEP-03 (overlay host) and issue (a).

**(a) Runtime: governed capture endpoint.** A bounded capture write path through the governed pipeline (policy → validation → deterministic writer) that appends a capture to the vault inbox note convention. This slice defines the bounded capture action on top of the existing governed machinery. The endpoint shape (new bounded action vs. deterministic append vs. ingest-queue reuse) is this issue's decision — the spec's invariants are normative: no due dates, no app task states, governed write only, runtime-produced acknowledgement. The runtime half has **no UI dependency** and may start in parallel with SEP-02/SEP-03.

> **Endpoint decision (shipped, #1790):** `POST /api/companion/capture` (`app/api/routes/capture.py`) — a new bounded action over the existing governed machinery, not ingest-queue reuse (the queue is asynchronous and cannot back a "written · \<inbox ref\>" acknowledgement). Pipeline: WriteGuard policy gate (`companion.capture.append`) → explicit schema validation (`extra="forbid"`; empty/whitespace text is a named rejection — never silently dropped) → deterministic append via `app.knowledge.write_ops.append_note_relative` → `capture.inbox.appended` outbox event. Inbox note convention: `<inbox_dir_rel>/inbox.md` (inbox dir per `app.vault.paths.get_vault_inbox_dir_rel`; `VAULT_CAPTURE_NOTE_REL` overrides), entries as timestamped bullets per `app/services/inbox.py` — no checkbox syntax. The acknowledgement surfaces the deterministic writer's `WriteReceipt` verbatim.

**(b) UI: capture modal.** A top modal on the overlay host, opened by `⌘N` / `capture.open`: a textarea (`data-region="capture-input"`), a "Capture to inbox" action (`capture.save`), and a session-capture list showing this session's captures with their written/not-yet-written state. **Offline honesty:** when the runtime is unreachable, the composer stays usable and each unwritten capture is plainly labeled not-yet-written; text is never silently dropped and a write is never claimed without runtime acknowledgement.

## Concretely

```text
⌘N → capture modal over the anchor
type + capture.save → governed append → session list shows "written · <inbox ref>"
runtime unreachable → composer still accepts; entry shows "not yet written"
no due-date field exists anywhere on the surface
```

## Why This Matters

Capture is where task-manager posture would creep in (due dates, states, nagging) and where silent data loss would be most corrosive (a captured thought that vanishes breaks trust in the whole prosthesis).

## Acceptance Criteria

- [ ] A capture routes through the governed pipeline and lands in the vault inbox per the convention; no direct vault I/O from the UI.
  Verify: `tests/api/test_capture_inbox_api.py::test_capture_appends_to_inbox_through_governed_pipeline`
- [ ] Captures carry no due date and no app-managed task state, at the endpoint and on the surface.
  Verify: `tests/api/test_capture_inbox_api.py::test_capture_has_no_task_semantics`
- [ ] `⌘N` opens the modal; a successful capture appears in the session list as written, with the runtime acknowledgement reference.
  Verify: `tests/companion_ui/test_capture_modal.py::test_capture_save_shows_written_state_from_runtime_ack`
- [ ] With the runtime unreachable, the composer stays usable and unwritten captures are labeled not-yet-written; no text is dropped and no write is claimed.
  Verify: `tests/companion_ui/test_capture_modal.py::test_offline_capture_is_honest_and_preserves_text`
- [ ] The modal dismisses to the anchor with unsent text preserved for the session.
  Verify: `tests/companion_ui/test_capture_modal.py::test_dismiss_preserves_unsent_text`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_capture_inbox_api.py` (issue a)
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_capture_modal.py` (issue b)
- `ruff check app tests`

## Out of Scope

- Due dates, reminders, recurring captures, task states, or any nagging mechanics.
- Triage of captured material (a separate cognitive surface).
- Durable offline queue with background sync — this slice is session-honest, not an offline-first store.
- Mobile dictation capture.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q17
- `companion-ui/docs/DESIGN_BRIEF.md` (Capture surface, source artifact)
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`

## Related GitHub Issues

Create **two** issues: `[SystemEntryPoint] capture-inbox-endpoint: governed capture append` (runtime; no UI dependency) and `[SystemEntryPoint] capture-modal: ⌘N capture UI` (depends on the endpoint issue and SEP-03).
