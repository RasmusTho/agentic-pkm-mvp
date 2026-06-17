---
name: Generate Co-Authoring Edit
description: Connect a write-capable co-authoring cognition to the existing CanvasWriter so a user intent plus the current note body produces a generated body edit that lands in place during an active session
task_id: AGENTIC-CANVAS-01
source_anchor: docs/CANVAS_CHAT_SURFACE/README.md :: What This Capability Builds
parent_capability: Agentic Canvas Co-Authoring
prerequisites: []
depends_on:
  - CO_AUTHOR_NOTE_BODY.md
  - EXPOSE_CANVAS_SESSION_API.md
  - GATE_GOVERNANCE_BEARING_MUTATIONS.md
can_parallelize_with: []
---

State: Implementation task specification. Adds the missing agent to the canvas surface: today `CanvasWriter.apply_edit` writes a caller-supplied `new_body`; nothing turns a user intent into that body. This task introduces a write-capable co-authoring cognition gated behind `CANVAS_ENABLED`.
Doc role: Implementation task spec
Authority: Implements the co-authoring intent class from `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`. Does not reopen the co-authoring/governance-bearing split.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-08

# Generate Co-Authoring Edit

## Purpose

The canvas runtime is plumbing without an agent. `app/chat/canvas_writer.py:57` (`apply_edit(session, new_body, change_summary)`) requires the caller to supply the finished body, and `app/chat/read_only_cognition.py` is deliberately execution-denied and never wired to the writer. The "co-author a note with an agent editing in place" experience — the reason Companion UI exists — is therefore unreachable. This task connects intent to a generated edit.

## What This Task Does

Introduces a **write-capable co-authoring cognition** that, during an active user-present canvas session, takes the user's natural-language intent plus the current note body (and optional retrieval context) and produces a generated new body, which is then applied through the existing `CanvasWriter` so all existing governance guards still hold.

- New module `app/chat/coauthoring_cognition.py`: a cognition that plans/generates a body revision via the shared `ReasoningFacade` (`app/reasoning/facade.py`). It is distinct from `read_only_cognition.py`: it is authorized to produce body text, but only body text.
- New endpoint `POST /api/canvas/sessions/{session_id}/coauthor` in `app/api/routes/canvas.py` taking `{intent, change_summary?}`. It runs the cognition, applies the generated body via `CanvasWriter.apply_edit`, appends the intent + change summary to the `.chats/` session log as provenance, and returns the applied body.
- The new path inherits every guard already enforced by `CanvasWriter`: active session required, in-vault note only, frontmatter rejected (a generated body containing frontmatter is a `GovernanceBearingMutationError`, routed to `GovernanceRouter`, never silently applied).

This is the co-authoring intent class from `DEFINE_CANVAS_COEDITING_MODEL.md`: authorized by user presence, bounded to the open note's body, reversible by the existing undo path, audited by the session log. It is **not** governance-bearing and does **not** loosen `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.

## Concretely

```
# Active session already opened on a note (POST /api/canvas/sessions)
POST /api/canvas/sessions/{id}/coauthor
{ "intent": "expand the decision section with the trade-offs we discussed" }

-> 200
{
  "session_id": "...",
  "applied_body": "<note body with an expanded decision section>",
  "change_summary": "expanded decision section",
  "generated": true
}
# .chats/<note-slug>/<ts>-coauthor.md gains an entry: intent + change summary
```

A frontmatter-bearing generation is refused, not applied:

```
POST .../coauthor  -> intent that would rewrite `type:`/`maturity`
-> 409 governance-bearing; routed to GovernanceRouter, body unchanged
```

## Why This Matters

Without this task the canvas API stays a write-pipe with no author. Every higher surface (the Companion UI canvas, hybrid Panel/Chat) would have to invent its own edit-generation path, fragmenting the authority model. Putting generation behind the existing `CanvasWriter` guards is what keeps "the agent edits in place" compatible with the gated-execution invariant.

## Acceptance Criteria

- [ ] A co-authoring cognition generates a body revision from `{intent, current_body}` and returns body-only text.
  Verify: `tests/chat/test_coauthoring_cognition.py::test_generates_body_from_intent`
- [ ] The cognition never emits frontmatter; a generation containing a frontmatter block is rejected before write.
  Verify: `tests/chat/test_coauthoring_cognition.py::test_generated_body_with_frontmatter_is_rejected`
- [ ] `POST /api/canvas/sessions/{id}/coauthor` applies the generated body through `CanvasWriter` and returns `applied_body`.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_applies_generated_body`
- [ ] The intent and change summary are appended to the active `.chats/` session log as provenance.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_appends_intent_to_session_log`
- [ ] A governance-bearing generation (frontmatter/cross-note) is routed to the gated pipeline, not applied in place.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_governance_bearing_is_routed_not_applied`
- [ ] The endpoint and cognition are inert unless `CANVAS_ENABLED` is set; default Core Runtime behavior is unchanged.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_requires_canvas_enabled`
- [ ] The read-only Chat cognition scaffold (`app/chat/read_only_cognition.py`) is unchanged and still execution-denied.
  Verify: `tests/chat/test_coauthoring_cognition.py::test_read_only_cognition_remains_execution_denied`

## How to Verify (Pre-Merge)

- `pytest -q tests/chat/test_coauthoring_cognition.py tests/api/test_canvas_coauthor_api.py`
- `ruff check app tests`
- `git diff --check`
- Manual: with `CANVAS_ENABLED=1`, open a session, POST a co-author intent, confirm the note body changes in place and the `.chats/` log records the intent.

## Out of Scope

- Any Companion UI surface (that is `SURFACE_CANVAS_IN_COMPANION_UI.md`).
- Streaming/token-level edit display. The endpoint returns the applied body; live streaming is a later refinement.
- Hybrid Panel/Chat routing beyond the existing `GovernanceRouter` handoff.
- Retention-window enforcement for session logs.
- Workspace mode (multi-note sessions).
- Changing `read_only_cognition.py` or making Core Runtime depend on this path.

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/README.md`
- `docs/CANVAS_CHAT_SURFACE/CO_AUTHOR_NOTE_BODY.md`
- `docs/CANVAS_CHAT_SURFACE/GATE_GOVERNANCE_BEARING_MUTATIONS.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` :: Authority Split
- `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md` (this is Agentic Lab, opt-in)
- `app/chat/canvas_writer.py`, `app/chat/governance_router.py`, `app/api/routes/canvas.py`, `app/reasoning/facade.py`

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/GENERATE_COAUTHORING_EDIT" and must preserve the co-authoring/governance-bearing split and the `CANVAS_ENABLED` gate.
