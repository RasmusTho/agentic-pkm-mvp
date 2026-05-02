---
name: Canvas Chat Surface
description: Implementation specification for the canvas-Chat co-editing surface — the user-facing capability that lets a user work on a note with an agent editing in place, like a collaborative editor.
type: specification
authority: SoT for the canvas-Chat runtime implementation; the authority spec for the co-editing posture, mutation split, and session-log conventions is docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md
source_of_truth: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md
related_docs:
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md
  - docs/HUMAN-FLOWS.md :: Case: I want to think on a note with a writing partner
  - docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
  - app/chat/read_only_cognition.py
  - app/knowledge/write_ops.py
---

State: Active specification with bounded implementation shipped behind `CANVAS_ENABLED`. Session logs, in-place body editing, governance-routing, and API/CLI session lifecycle landed via PRs #605/#618/#619/#626; owner-doc promotion now records the surface as materially supported while hybrid Panel/Chat behavior remains future work.
Owner: v6.0 architecture owner
Last reviewed: 2026-04-30

# Canvas Chat Surface

## What This Capability Builds

A user opens a note in the vault and starts a canvas session. The agent edits the note body directly, in place, as they collaborate — the way a second author would. The user does not review a diff; they see edits appear. The session closes. The note retains the result. A session log in `.chats/<note-slug>/` captures the intent trail.

This is the human flow described in `docs/HUMAN-FLOWS.md` §8: "I want to think on a note with a writing partner."

## What This Capability Does Not Build

- A UI or editor library. Hosting location (Obsidian, standalone, web) is deferred.
- Workspace mode (multi-note sessions across related notes).
- Hybrid Panel/Chat integration. That is a separate downstream capability.
- Retention policy enforcement. Retention window duration is a policy decision deferred to a later slice.
- The full Deep Agent cognition stack. The read-only cognition scaffold (`app/chat/read_only_cognition.py`) is the starting point; this capability adds the write path and session lifecycle on top.

## Governing Authority

**Do not reopen or contradict these decisions while implementing:**

- `DEFINE_CANVAS_COEDITING_MODEL.md` — the posture, mutation split, `.chats/` conventions, and note↔session cardinality. This spec does not override any of it.
- `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` — governance-bearing mutations (frontmatter, cross-note, lifecycle) always go through the gated pipeline regardless of user presence.
- `DEFINE_CHAT_AUTHORITY_BOUNDARY.md` — Chat is canvas, not Q&A. Co-authoring is authorized by user presence; it does not bypass gated execution.

## Implementation Tasks

Execute in this order. Each task is independently mergeable.

| Order | Task File | What It Builds | T-shirt | Parallelizable |
|-------|-----------|----------------|---------|----------------|
| 1 | [WRITE_SESSION_LOGS.md](WRITE_SESSION_LOGS.md) | Session log writer + `type: chat-session` artifact class | XS | — |
| 2 | [CO_AUTHOR_NOTE_BODY.md](CO_AUTHOR_NOTE_BODY.md) | In-place body editing path through KnowledgePort | M | — |
| 3 | [GATE_GOVERNANCE_BEARING_MUTATIONS.md](GATE_GOVERNANCE_BEARING_MUTATIONS.md) | Canvas-session mutations routed through gated pipeline | S | — |
| 4 | [EXPOSE_CANVAS_SESSION_API.md](EXPOSE_CANVAS_SESSION_API.md) | Bounded API surface for canvas session open/edit/close | S | — |

## Execution Order

```
WRITE_SESSION_LOGS
        ↓
CO_AUTHOR_NOTE_BODY
        ↓
GATE_GOVERNANCE_BEARING_MUTATIONS
        ↓
EXPOSE_CANVAS_SESSION_API
```

No task in this capability is parallel-safe with another within this capability; each builds on the writer path established by the previous.

## Acceptance

The parent capability is accepted when all of the following are true:

- [x] A canvas session can be opened on a vault note and body edits apply in place without a diff-review gate.
- [x] Session logs are written to `vault/.chats/<note-slug>/<timestamp>-<label>.md` with correct `type: chat-session` frontmatter.
- [x] Governance-bearing mutations (frontmatter, cross-note, lifecycle) from a canvas session route through the gated-execution pipeline — not through the co-authoring path.
- [x] The co-authoring path is blocked from writing frontmatter classification fields, creating/deleting/renaming notes, or writing to notes other than the currently-open one.
- [x] A bounded API surface exists for session open, body edit, and session close.
- [x] The existing read-only cognition scaffold (`app/chat/read_only_cognition.py`) is not broken.
- [x] Focused tests cover each of the four surfaces above.
- [x] `docs/HUMAN-FLOWS.md` §14 moves canvas-Chat from "Emerging but not yet fully realized" to the "Already materially supported" list.
- [x] `docs/STATUS.md` records the delivery receipt.

## Pointer to Parent Feature Issue

Parent feature issue: **#597** — live validation hub; closes only after owner-doc promotion.

Implementation task issues (in execution order):

| Task | Issue | Status |
|------|-------|--------|
| WRITE_SESSION_LOGS | #598 | `closed` |
| CO_AUTHOR_NOTE_BODY | #599 | `closed` |
| GATE_GOVERNANCE_BEARING_MUTATIONS | #600 | `closed` |
| EXPOSE_CANVAS_SESSION_API | #601 | `closed` |
