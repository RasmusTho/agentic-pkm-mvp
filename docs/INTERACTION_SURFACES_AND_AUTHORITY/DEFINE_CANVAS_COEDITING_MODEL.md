---
name: Define Canvas Co-Editing Model
description: Specify the direct in-place editing posture for canvas Chat, the co-authoring authority model, the one-to-many note↔session relationship, the session-as-provenance pattern, and the .chats/ + type: frontmatter conventions
task_id: INTERACTION-07
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md :: Decision (Candidate A)
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01, INTERACTION-03, INTERACTION-05, INTERACTION-06]
depends_on:
  - NAME_THE_THREE_INTERACTION_SURFACES.md
  - DEFINE_CHAT_AUTHORITY_BOUNDARY.md
  - RECONCILE_CHAT_MUTATION_AUTHORITY.md
  - STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md
can_parallelize_with: []
---

State: Specification draft. Docs-only. Extends the Candidate A decision recorded in `RECONCILE_CHAT_MUTATION_AUTHORITY.md` with the concrete co-editing posture, the authority split between co-authoring and governance-bearing mutation, and the file-system conventions for chat-session artifacts.
Doc role: Spec
Authority: SoT for the canvas-Chat co-editing posture and the system-owned chat-session artifact class. Binding on any runtime implementation of a canvas Chat surface.
Owner: v6.0 architecture owner
Last reviewed: 2026-04-20
Last verified against: RECONCILE_CHAT_MUTATION_AUTHORITY.md §Decision, DEFINE_CHAT_AUTHORITY_BOUNDARY.md, STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/HUMAN-FLOWS.md, docs/research/CHAT_SURFACE_BUILD_VS_BUY.md

# Define Canvas Co-Editing Model

## Purpose

State how the canvas Chat surface behaves when a user is editing a note with assistance: directly, in place, live, like a collaborative editor. Name the authority model that makes that safe without collapsing the gated-execution invariant. Name the artifact class that captures intent-trail provenance for those sessions, and the file-system conventions that keep chat artifacts subordinate to the vault.

This spec is a downstream extension of `RECONCILE_CHAT_MUTATION_AUTHORITY.md` Candidate A. It does not reopen the mutation-authority decision; it describes how that decision expresses itself in a co-editing workflow.

## What This Task Does

Produces a specification that states:

1. **The co-editing posture.** Canvas Chat applies edits directly to the open note as they are generated, without a pre-commit approval step. The note is the durable surface; the chat is not a proposal queue. The user's experience is of co-authoring a document, not of reviewing diffs.
2. **The authority split.** Two distinct mutation classes, each with its own governance model:
   - *Content co-authoring* within the currently-open note during an active session: authorized by user presence, rolled back by undo, audited by the session log.
   - *Governance-bearing mutations* (frontmatter `type:`/classification fields, cross-note operations, note creation/deletion/rename, promotion of maturity or commitment state): flow through the gated-execution pipeline named in `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.
3. **The note↔session relationship.** One-to-many: one note, many short purposeful sessions over time. Each session is ephemeral; the note is the persistent memory across sessions. Long-lived chats that accumulate semantic value are explicitly out of scope because they reintroduce the failure mode of the chat log becoming a shadow source of truth.
4. **The artifact classes.** The note is the *artifact* (primary, curated, canonical). The session log is the *provenance* (retained, subordinate, captures intent). The relationship is the same as code-to-commit-message: both are retained, but they are different classes of thing and only one of them is the load-bearing artifact.
5. **The file-system conventions.** Session logs live under `vault/.chats/<note-slug>/<timestamp>-<short-label>.md`. Classification is carried in frontmatter as `type: chat-session`. The `.chats/` namespace keeps system-generated artifacts out of the human writing surface; the `type:` field lets Obsidian search, Dataview, graph view, and system retrieval distinguish artifact from exhaust.
6. **Retention and reversibility.** Session logs are retained by default but bounded: a retention window (to be named) after which sessions are soft-deleted unless explicitly preserved. Retention is per-note: when a note is deleted, its session history becomes eligible for the same disposition as the note.

## The Canvas Co-Editing Posture

### Direct in-place editing, not suggest-then-accept

Canvas Chat edits apply to the open note immediately as they are generated. The user does not review a diff before each change lands. The editor behaves like a live collaborative editor where the assistant is the second author.

This is deliberate. The canvas posture is *externalize and manipulate thought*, not *review and approve suggestions*. A diff-review gate would reimport ASK-shaped turn-taking under a different name and defeat the canvas-vs-ASK distinction this capability protects.

Undo is the per-edit rollback mechanism. Autosave to the vault file is continuous — Obsidian's file watcher picks up saves normally, no plugin required.

### The session, not the turn

A canvas session is the unit of work. Sessions are short and purposeful: "clean this up," "expand the decision section," "restructure into context/decision/implications." A session opens, edits accumulate in place, the session closes, and the note reflects the accumulated work.

The chat transcript inside the session is not the thing the user operates on — the note is. The chat transcript is an intent trail that the system captures for later retrieval, not a document the user will return to as their canonical memory.

## The Authority Split

Candidate A records that Chat may carry governed mutation rights through the same pipeline as Panel. This spec names the split that makes direct in-place editing compatible with that decision.

### Co-authoring: authorized by presence

The following mutations occur within the active co-authoring mode:

- edits to the body of the currently-open note,
- rearrangement, insertion, or deletion of content within that note,
- in-note formatting and prose-level revision,
- any edit the user could equivalently make by typing themselves.

These are authorized by the fact that the user is actively present in the session. The authority class is the same as the user's own keystrokes — the assistant is a second author, and the user's presence is the authorization signal. The session log is the audit record; undo is the rollback mechanism.

This does not bypass the gated-execution invariant. It recognizes that user-present co-authoring is a distinct mutation class from autonomous system action, and that the invariant applies to the latter class.

### Governance-bearing: flows through the gated pipeline

The following mutations do **not** fall under co-authoring and must route through the gated-execution pipeline regardless of user presence:

- changes to frontmatter fields that carry classification or governance meaning (`type:`, `maturity`, `review_state`, `kind`, scope/sphere tags),
- cross-note operations (edits to notes other than the currently-open one, multi-note synthesis that writes to other files),
- note lifecycle transitions (creation of new notes, renames, moves between folders, deletions, archival),
- promotions of maturity or commitment state,
- operations against system-owned artifacts (companion notes, receipts, chat-session logs themselves).

These are *the same actions Panel would take through its proposal flow*. Candidate A's decision — that Chat-originated governance-bearing mutations land their receipts in Panel's gated-execution pipeline locality — applies to this class.

### The line between them

The distinction is not stylistic or judgement-based. It is defined by scope:

> Co-authoring is "within this note's body, during this session, with the user present." Anything outside that scope is governance-bearing.

When an action is ambiguous, it is treated as governance-bearing. The default failure mode is caution, not fluidity.

## The Note↔Session Relationship

### One-to-many

One note, many sessions over time. Each session is short, focused on a single editing intent. Sessions close and the note persists.

Long-lived chats per note are explicitly out of scope. They look attractive because the chat accumulates context, but they introduce the failure mode the architecture is built to prevent: the chat log becomes the document the user needs to consult to understand the note's history, and the note is silently demoted to a derived artifact.

### The note is the persistent memory

Continuity across sessions is carried by the note itself, not by a long-running chat. A new session opens the note, reads its current state, and has everything it needs. If a decision made in session 1 matters for session 3, it lives in the note.

This makes each session self-contained and makes the note's own evolution the load-bearing history.

### Workspace mode: a bounded exception

There is a legitimate use case for longer-lived sessions that span multiple notes — cross-note synthesis, reconciliation of related material, thematic review. This is workspace mode.

Workspace mode is out of scope for the initial canvas co-editing capability but is named here so it does not silently grow without spec. When it ships, it inherits the same artifact-vs-provenance model: the output lands back in a note (new or existing), the session is provenance, the note is the artifact. Workspace-mode edits to multiple notes are *governance-bearing by definition* (they are cross-note operations) and must flow through the gated pipeline, even if the interaction feels co-authoring-like.

## Artifact Classes

### The note: artifact

- The durable, canonical, curated object.
- What the system retrieves, surfaces, links, and treats as the primary record.
- What the user reads, writes, and cites.
- What must remain understandable without the current system.

### The session log: provenance

- A retained intent trail capturing *why* the note evolved the way it did.
- Contains the user's prompts (intent), a summary of what changed (diff or description), and a timestamp.
- Not the full LLM response body — that is noise, not provenance.
- Readable by humans if consulted, but not part of normal browsing.
- Subject to retention policy.

The relationship mirrors code-to-commit-message: both are kept, both are useful, but the code is the artifact and the commit messages are the history of intent behind it.

## File-System Conventions

### Location: `.chats/`

Session logs live inside the vault under a system-owned namespace:

```
vault/
  notes/
    v6-architecture.md         ← artifact (primary human surface)
  .chats/
    v6-architecture/
      2026-04-20T14-30-restructure.md    ← provenance
      2026-04-11T09-15-initial-draft.md
```

Reasoning:

- **In-vault** so sessions sync, back up, and are locally searchable alongside the notes they describe. The same local-first, device-portable guarantees that apply to notes apply to their provenance.
- **Dotfile-prefixed (`.chats/`)** so Obsidian, Dataview, and the user's normal browsing ignore the directory by default. The user can opt in to viewing it, but does not encounter it while writing.
- **Per-note subdirectory** so the one-to-many relationship is visible in the file system and retention operations are straightforward.

### Classification: `type:` frontmatter

Chat-session logs carry a `type:` field in their frontmatter as the classification signal:

```yaml
---
type: chat-session
note: "[[v6-architecture]]"
date: 2026-04-20T14:30
session_id: <uuid>
---
```

The `type:` field is system-assigned and governance-bearing. It is distinct from user-managed `tags:`, which remain the user's authorship surface.

This spec introduces `type:` as the classification mechanism for the chat-session artifact class. It proposes — but does not unilaterally adopt — `type:` as a shared convention for other system-owned artifact classes. The companion-note contract (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`) does not currently declare a `type:` field; adopting `type: companion` there would require a separate owner-doc promotion of the companion-note contract and is explicitly out of scope for this spec. Until that promotion happens, `type:` is a chat-session field only.

### Obsidian integration

The `type: chat-session` field and the `.chats/` namespace together let chat-session artifacts be handled in the user's normal tools:

- Dataview can filter them out of views with `WHERE type != "chat-session"`.
- Graph view can hide them by tag/type group.
- Obsidian search can exclude the `.chats/` folder.
- System retrieval uses `type: chat-session` to distinguish artifact from exhaust.

If `type:` is later adopted by the companion-note contract, the same filters extend to those artifacts without change.

## Retention and Reversibility

### Default retention

Session logs are retained by default. The canvas surface does not create them for transient display and then discard them — the retention is part of the provenance contract.

### Bounded retention

A retention window (duration to be named during implementation) after which old sessions are eligible for soft deletion unless explicitly preserved. The user can pin a session to keep it indefinitely.

### Deletion of a note

When a note is deleted, its session history becomes eligible for the same disposition. The default is that session logs follow the note's lifecycle; explicit preservation overrides this.

### Reversibility at the docs layer

This spec is reversible at the docs layer until the first canvas-Chat co-editing runtime slice is implemented. After that point, changes to the artifact-vs-provenance split or the `.chats/` convention require migration, not just doc edits.

## What This Spec Does Not Do

- Does not describe a runtime implementation. The editor library, the streaming protocol, the Obsidian-vs-standalone location question, and the backend routing are all deferred to the implementation lane.
- Does not name the retention window duration. That is a policy decision for the retention-policy lane.
- Does not define the exact session-log schema beyond the minimum fields above (`type`, `note`, `date`, `session_id`, user prompts, change summary).
- Does not specify the governance-bearing receipt shape. That inherits from Panel's receipts (per `RECONCILE_CHAT_MUTATION_AUTHORITY.md` Decision) and will be named by the canvas-commit capability lane when a cross-note or frontmatter mutation is first implemented.
- Does not pick the UI primitive (CodeMirror, ProseMirror, or another editor). That is an implementation choice.
- Does not authorize workspace mode. Workspace mode is named as a future capability and inherits this spec's artifact-vs-provenance split when it ships.

## Why This Matters

Canvas Chat will feel like a collaborative editor to the user. If the authority model is not named before the runtime ships, one of two failure modes is likely:

1. *Over-restriction.* The implementer treats every edit as governance-bearing and adds a pre-approval gate, which reintroduces ASK-shaped turn-taking and defeats the canvas posture.
2. *Over-permissiveness.* The implementer treats all Chat-originated actions as co-authoring and lets the assistant rewrite frontmatter, move notes, or mutate other notes without governance, which collapses the gated-execution invariant.

Naming the co-authoring/governance-bearing split in docs, before the first runtime slice, makes both failure modes structurally harder.

The `.chats/` and `type:` conventions serve the same purpose for persistence: they prevent session logs from either being lost (no retention) or from polluting the human writing surface (unnamespaced). Either failure would make the vault less trustworthy as a writing environment.

## Acceptance Criteria

- [ ] The spec names direct in-place editing as the canvas posture and explicitly rejects suggest-then-accept as the default interaction.
- [ ] The spec names exactly two mutation classes (co-authoring, governance-bearing) and gives a scope-based definition of the boundary.
- [ ] The spec names the one-to-many note↔session relationship and explicitly rejects long-lived per-note chats.
- [ ] The spec names the note as artifact and the session log as provenance, with the code/commit-message analogy.
- [ ] The spec names `.chats/<note-slug>/` as the session log location and `type: chat-session` as the classification mechanism.
- [ ] The spec cites `RECONCILE_CHAT_MUTATION_AUTHORITY.md` §Decision and does not reopen or contradict Candidate A.
- [ ] The spec cites `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` and does not loosen the gated-execution invariant.
- [ ] The spec names what it does not do (runtime, retention window, exact schema, receipt shape, UI primitive, workspace mode).

## How to Verify (Pre-Merge)

Docs review:

- A reviewer can quote a sentence that says canvas edits apply directly, not through a diff-review gate.
- A reviewer can quote the scope-based definition of co-authoring vs governance-bearing.
- A reviewer can state the artifact-vs-provenance distinction and the note↔session cardinality.
- A reviewer can point to the `.chats/` convention and the `type:` frontmatter field without finding conflicting guidance elsewhere in this directory.
- A grep for "suggest-then-accept" or "diff-review" returns only rejection language in this file.
- No part of this spec picks a runtime, UI library, retention window, or hosting location.

## Out of Scope

- Implementing the canvas Chat surface.
- Choosing an editor primitive or UI framework.
- Deciding the hosting location (inside Obsidian, standalone web app, other).
- Naming the retention window duration.
- Defining the governance-bearing receipt schema.
- Implementing workspace mode.
- Modifying the companion-note contract beyond naming the shared `type:` field convention.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md` §Decision
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md` §Chat Authority Boundary
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` §The Three Surfaces :: Chat
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` :: externalize and manipulate thought
- `docs/HUMAN-FLOWS.md` §8 (scenario), §13 (surfaces)
- `docs/research/CHAT_SURFACE_BUILD_VS_BUY.md` §F, §G (phased path to custom canvas)

## Related GitHub Issues

If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL" and must preserve the co-authoring/governance-bearing split recorded here.

---

**Status:** Specification draft. Extends Candidate A with the concrete co-editing posture and the system-owned chat-session artifact class. Runtime implementation remains out of scope here.
