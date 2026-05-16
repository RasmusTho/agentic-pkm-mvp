---
name: Canvas Agent MVP Surface Contract
description: Normalized contract for the Canvas Agent MVP interaction surface in Companion UI — co-authoring posture, session lifecycle, authority model, provenance conventions, and governance escape hatch
doc_role: Surface contract
authority: SoT for Canvas Agent MVP surface definition. Binding on any Companion UI implementation of the Canvas co-authoring surface.
owner: v6.0 architecture / Companion UI product
last_reviewed: 2026-05-16
last_verified_against: |
  docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md,
  docs/COMPANION_UI_PRODUCT_SPEC.md,
  companion-ui/docs/UI_RUNTIME_BOUNDARIES.md,
  companion-ui/docs/CANVAS_SUGGESTION_FLOW.md,
  companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md
governing_issue: "#1021"
related_issues: "#1022 (epic), #868–#874 (Canvas bounded suggestion flow), #995/#996/#1019 (Panel in Companion UI)"
---

# Canvas Agent MVP Surface Contract

## Why Canvas Agent Is the Primary Reason Companion UI Exists

Canvas Agent is the primary reason Companion UI exists. Panel can be supported inside Obsidian as a
markdown/governance surface. Automation runs headlessly. But Canvas co-authoring requires a
live-editor environment — a session context, an undo stack, an active-user-presence signal, and
overlay/rail/sheet affordances for provenance and escape-hatch routing — that plain Obsidian markdown
cannot provide without plugin-level UI infrastructure.

Companion UI provides that environment. Every other Companion UI surface is secondary to Canvas Agent
co-authoring as a justification for the product's existence.

This does not demote Panel. Panel is a first-class Companion UI surface. The two must not be
collapsed. They are named here as distinct because the pressure to collapse them is real: both appear
"in the note area," both involve the assistant, and both produce artifact-local outputs. They remain
distinct because they serve categorically different cognitive functions.

## Surface Definitions (Non-Collapsible)

### Canvas Agent

**Canvas is the co-authoring and thinking surface.** The user and assistant work together in the
body of the currently open artifact during an active user-present session. Canvas is direct,
in-place, and live. It does not require pre-commit approval for every body edit. Undo and session
provenance are the safety mechanisms for body edits.

Canvas serves the user need: _externalize and manipulate thought_.

### Panel (for contrast — not defined here)

**Panel is the artifact-local intent manifestation and confirmation surface.** The agent surfaces
what it believes the user likely wants to do with a specific artifact before the user confirms,
corrects, or rejects that intention. Confirmed intent enters governed execution. Panel is
proposal-oriented before confirmation, receipt-oriented at the execution boundary.

Panel is defined in: `#995`, `#996`, `#1019`, and
`docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`.

**Canvas and Panel must not be collapsed.** See [Distinction from Panel](#distinction-from-panel).

### Canvas Bounded Suggestion Flow (for contrast — not defined here)

Canvas bounded suggestion flow is a staged suggestion pattern for discrete proposals and
governance-bearing escape hatches. It is not the default Canvas co-authoring model.

Canvas bounded suggestion flow is defined in: `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` and
`#868–#874`.

**Canvas core co-authoring and Canvas bounded suggestion flow must not be collapsed.** See
[Distinction from Canvas Bounded Suggestion Flow](#distinction-from-canvas-bounded-suggestion-flow).

---

## Primary Working Surface: Active Note / Artifact Body

The active note body is the primary working surface for Canvas Agent co-authoring.

- The note is the **canonical artifact**. It is durable, curated, and the load-bearing record.
- The chat/session transcript is **subordinate provenance**. It captures intent trail but must not
  become the canonical artifact.
- The relationship mirrors code-to-commit-message: both are retained, both are useful, but the code
  is the artifact and commit messages are the intent history behind it.
- The user's experience is of co-authoring a document with an assistant — not of reviewing a
  proposal queue.

A Canvas session operates on **one note at a time**. Cross-note operations are
governance-bearing by definition and must not occur through the Canvas co-authoring path.

---

## Canvas Session Lifecycle

A Canvas session is the unit of work. Sessions are short and purposeful.

### Session States

| State | Description |
|---|---|
| `start` | Session initiated; the current note is the active surface; assistant is ready to co-author. |
| `active` | Session in progress; user is present; body edits may be applied directly in place. |
| `paused` / `interrupted` | Session suspended (user left, device locked, browser hidden, network drop); no new edits applied; session remains recoverable; session log captures the interruption point. |
| `closed` | Session complete; note reflects accumulated work; session log is written to `.chats/<note-slug>/`; undo history scoped to this session may be bounded after close. |

### Session Cardinality

One note, many sessions over time. Each session is short and focused on a single editing intent.
The note persists across sessions; sessions are the intent trail behind the note's evolution.

Long-lived chats per note are explicitly out of scope. A long-lived chat that accumulates semantic
value reintroduces the failure mode the architecture is built to prevent: the chat log becomes the
document the user needs to consult to understand the note's history, and the note is silently
demoted to a derived artifact.

---

## User-Present Authority for Body Co-Authoring

Body edits during an active Canvas session are authorized by **user presence**. The authority class
is the same as the user's own keystrokes — the assistant is a second author, and the user's active
session is the authorization signal.

This is not a bypass of the gated-execution invariant. User-present co-authoring is a distinct
mutation class from autonomous system action. The gated-execution invariant, as defined in
`docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`, applies to
autonomous system action, not to user-present co-authoring of note body content.

**Permitted under user-present authority during an active Canvas session:**

- Edits to the body of the currently open note.
- Rearrangement, insertion, or deletion of content within that note.
- In-note formatting and prose-level revision.
- Any edit the user could equivalently make by typing themselves.

**Not permitted under user-present authority (governance-bearing — see below):**

- Changes to frontmatter fields (`type:`, `maturity`, `review_state`, `kind`, scope/sphere tags).
- Cross-note operations.
- Note lifecycle transitions (creation, rename, move, delete, archive).
- Promotions of maturity or commitment state.
- Mutations of system-owned artifacts (companion notes, receipts, prior session logs).

---

## Direct In-Place Body Editing as the Default Canvas Posture

**Canvas core co-authoring applies body edits directly in place.** The user does not review a diff
before each change lands. The editor behaves like a live collaborative editor where the assistant is
the second author.

This is deliberate. The Canvas posture is _externalize and manipulate thought_, not
_review and approve suggestions_. A diff-review gate would reimport suggest-then-accept turn-taking
under a different name and defeat the Canvas-vs-Panel distinction this surface protects.

**Core Canvas co-authoring is not suggest-then-accept by default.**

Canvas bounded suggestion flow (`#868–#874`) introduces a staged suggestion pattern for cases where
pre-commit preview is appropriate (bounded body-edit proposals, governance-bearing escape hatches).
That pattern is opt-in and scoped — it does not define the default Canvas interaction model.

---

## Undo / Rollback for Assistant-Applied Body Edits

**Undo is the rollback path for body co-authoring edits.**

Because body edits apply directly in place, the user's primary safety mechanism is the undo stack.
Undo must be available for all assistant-applied body edits within an active Canvas session.

The session log (see [Session Provenance](#session-provenance)) is the audit record of what changed
and why. Undo is the interaction-time rollback mechanism.

Implementation implications (deferred to implementation lane):

- The undo stack should distinguish user keystrokes from assistant-applied edits to support
  selective rollback where the editor primitive allows it.
- After session close, undo history for that session may be bounded; the session log remains the
  durable provenance record.
- Undo does not bypass session log retention; rolled-back edits remain visible in provenance.

---

## Session Provenance under `.chats/<note-slug>/...`

### Note as Artifact, Session as Provenance

The note is the artifact. The session log is the provenance. They are two distinct artifact classes
and must not be conflated.

The session log captures:
- User prompts (intent).
- A summary of what changed (diff or description).
- Timestamps.
- Session metadata (`session_id`, linked note reference).

The session log does **not** store the full LLM response body — that is noise, not provenance.

### File-System Convention

```
vault/
  notes/
    my-note.md                          ← artifact (canonical, primary)
  .chats/
    my-note/
      2026-05-16T10-30-cleanup.md       ← provenance (session log)
      2026-04-20T14-30-restructure.md
```

- **In-vault** so sessions sync, back up, and are locally searchable alongside the notes they
  describe.
- **Dotfile-prefixed (`.chats/`)** so Obsidian, Dataview, and the user's normal browsing ignore
  the directory by default.
- **Per-note subdirectory** so the one-to-many relationship is visible in the file system and
  retention operations are straightforward.

### Session Log Frontmatter

```yaml
---
type: chat-session
note: "[[my-note]]"
date: 2026-05-16T10:30
session_id: <uuid>
---
```

The `type: chat-session` field is system-assigned and governance-bearing. Session log writing is
implemented in `app/chat/session_log.py` (`SessionLogWriter.open_session()` / `append_turn()` /
`close_session()`); the write contract is specified in
`docs/CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS.md`. The `.chats/` namespace
and `type: chat-session` field together let session artifacts be filtered from normal vault views
and distinguished from human-authored notes by retrieval and system tooling.

### Provenance Is Subordinate

The session log is provenance, not the canonical artifact. A reader who needs to understand the
note reads the note. The session log is consulted when the reader needs to understand _why_ the
note evolved the way it did — it is the intent trail, not the output.

---

## Governance-Bearing Escape Hatch

Canvas is not a general-purpose mutation surface. The following mutations are **blocked** from the
Canvas co-authoring path and must be routed through the governed execution pipeline, regardless of
user presence:

| Blocked mutation class | Reason |
|---|---|
| Frontmatter classification fields (`type:`, `maturity`, `review_state`, `kind`, scope tags) | Governance-bearing; system-assigned or human-confirmed through Panel |
| Cross-note operations | Outside the currently-open note body; governance-bearing by definition |
| Note lifecycle transitions (create, rename, move, delete, archive) | Lifecycle state changes; governed by policy and WriteGuard |
| Promotions of maturity or commitment state | Require explicit human authority; must not be applied by co-authoring |
| Companion notes | System-owned artifact class |
| Receipts | System-owned artifact class; produced by governed execution |
| Prior session logs | System-owned provenance artifact; must not be user-directed or autonomously edited |
| System artifacts | Any system-owned artifact outside the user's note body |

When a Canvas session encounters a governance-bearing operation (e.g., the user asks the assistant
to change the note's lifecycle state or create a related note), the Canvas Agent must:

1. Recognize the operation as governance-bearing.
2. Surface the intent through the governance-bearing escape hatch (Canvas bounded suggestion flow
   queue path or Panel, depending on the operation class).
3. Not apply the mutation directly within the Canvas co-authoring path.

Ambiguous cases default to governance-bearing. The default failure mode is caution, not fluidity.

The gated-execution invariant is defined in:
`docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.
This contract does not loosen it.

---

## Distinction from Panel

| Dimension | Canvas Agent | Panel |
|---|---|---|
| **Cognitive function** | Co-authoring and thinking; externalize and manipulate thought | Artifact-local intent manifestation; agent surfaces likely next action for user to confirm |
| **Default interaction posture** | Direct in-place body editing; no pre-commit approval | Proposal-first; user confirms, corrects, or rejects before anything changes |
| **Who initiates** | User enters a session and co-authors actively | Agent manifests a likely intention; user recognizes or formulates a response |
| **Primary output** | Evolved note body | Confirmed intent entering governed execution |
| **Safety mechanism** | Undo + session provenance | Pre-commit confirmation + governed execution receipt |
| **Receipt locality** | Session log under `.chats/` | In-note receipt via governed execution pipeline |
| **Scope** | Currently open note body during active session | Artifact-local intent and lifecycle decisions |
| **Panel-in-Canvas overlap** | Canvas governance-bearing escape hatches may route through Panel or governed execution | Panel operates on the artifact's system lifecycle, not its body prose |

Panel must also be supported in Companion UI as a first-class surface. Panel support in Companion
UI is defined by `#995`, `#996`, and `#1019`. Those issues define Panel's render contract and
confirmation write-back.

**The defining difference:** Canvas co-authors the artifact body. Panel governs what the artifact
_becomes_ or _does_ as a system artifact.

---

## Distinction from Canvas Bounded Suggestion Flow

Canvas bounded suggestion flow (`#868–#874`, `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`) is a
staged suggestion pattern. It is **not** the default Canvas co-authoring model.

| Dimension | Canvas Core Co-Authoring (this contract) | Canvas Bounded Suggestion Flow (#868–#874) |
|---|---|---|
| **Default posture** | Direct in-place body editing | Stage → preview → apply/queue/discard |
| **Pre-commit approval** | Not required for body edits | Required; staging is the unit of interaction |
| **Governance-bearing** | Routed to escape hatch | Governance proposals queued, never applied directly |
| **State machine** | Session lifecycle (start/active/paused/closed) | `idle / thinking / staged_body / staged_governance / ...` |
| **Use case** | Flowing co-authoring of note body prose | Bounded discrete proposals; governance-bearing suggestions |
| **Governing issues** | #1021 (this contract) | #868–#874 |
| **Spec location** | This file | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` |

Canvas bounded suggestion flow is a valid Canvas family interaction pattern. It must not be
misread as the default. An implementation that treats every Canvas body edit as a staged proposal
requiring pre-commit approval violates the Canvas core co-authoring posture defined here.

Canvas bounded suggestion flow is the appropriate path for:
- Bounded body-edit previews where the user wants to preview before applying.
- Governance-bearing suggestions that must be queued rather than applied.
- Escape-hatch routing when co-authoring produces a governance-bearing operation.

---

## Implementation-Readiness Boundaries

This contract is docs-only. The following are **not** decided here:

- Editor library (CodeMirror, ProseMirror, or other).
- Streaming protocol between assistant and editor.
- Hosting location (inside Obsidian, standalone web app, other).
- Retention window duration for session logs.
- Exact session log schema beyond the minimum fields above.
- Governance-bearing receipt shape for Canvas-originated escape hatches.
- Workspace mode (multi-note sessions — named as a future capability, out of scope here).
- Undo stack implementation details beyond the requirement that undo covers assistant-applied edits.

### Open Questions for Implementation Lane

1. **Undo granularity.** Should the undo stack distinguish assistant-applied edits from user
   keystrokes? If so, how is the boundary surfaced to the user?
2. **Session recovery after interruption.** What is the minimum continuity payload needed to
   restore an interrupted Canvas session to `active` state? Note: session log write timing is
   already specified and shipped — `SessionLogWriter.open_session()` is called at session start and
   `append_turn()` is called per turn (see `app/chat/session_log.py` and
   `docs/CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS.md`). The open question is only the additional
   recovery payload: what Companion UI must persist so re-entry into a paused session is low-cost.
3. **Conflict resolution.** If the user edits the note externally (Obsidian) while a Canvas
   session is `paused`, what is the merge/conflict protocol?
4. **Session log retention policy.** What is the retention window after which sessions are eligible
   for soft deletion? How does note deletion cascade to session log eligibility?
5. **Escape hatch routing.** When Canvas detects a governance-bearing operation request, does it
   route to Panel (for artifact-lifecycle decisions) or to Canvas bounded suggestion flow queue
   (for body-adjacent governance proposals)? The routing rule needs a concrete decision before
   implementation.
6. **Session log schema.** Beyond `type`, `note`, `date`, `session_id`, what fields are required?
   User prompts, change summaries, applied/undone edit markers?

---

## Acceptance Criteria

- [x] Contract states Canvas Agent is the primary reason Companion UI exists and names the
  capabilities that require a live editor environment.
- [x] Contract defines the active note/artifact body as the primary working surface and the note
  as the canonical artifact.
- [x] Contract defines the Canvas session lifecycle: start, active, paused/interrupted, closed.
- [x] Contract defines user-present authority for body co-authoring and its scope boundary.
- [x] Contract defines direct in-place body editing as the default Canvas posture and explicitly
  rejects suggest-then-accept as the default.
- [x] Contract defines undo as the rollback path for assistant-applied body edits.
- [x] Contract defines session provenance under `.chats/<note-slug>/...` and keeps it subordinate
  to the note.
- [x] Contract defines the governance-bearing escape hatch and the blocked mutation classes.
- [x] Contract distinguishes Canvas from Panel.
- [x] Contract distinguishes Canvas core co-authoring from Canvas bounded suggestion flow.
- [x] Contract names implementation-readiness boundaries and open questions.

---

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` — upstream authority
  for co-editing posture, note↔session relationship, and `.chats/` conventions.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md` — Chat canvas framing
  and co-authoring/governance-bearing split.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` — Panel, Chat,
  Automation surface definitions and non-collapsibility argument.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` — gated-
  execution invariant; this contract does not loosen it.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` — Chat/Panel
  integration boundary.
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — Companion UI product model (Canvas is primary surface).
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — cognitive boundary constraints and integration
  boundary rules.
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — Canvas bounded suggestion flow spec (#868–#874).
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` — design handoff → normalized spec → issue → PR
  crossing rules.

## Governing Issues

- `#1021` — this contract
- `#1022` — [Epic] Companion UI / UX surface implementation map
- `#868–#874` — Canvas bounded suggestion flow implementation
- `#995`, `#996`, `#1019` — Panel in Companion UI

---

**Status:** Normalized contract. Docs-only. Ready for implementation issue creation.
