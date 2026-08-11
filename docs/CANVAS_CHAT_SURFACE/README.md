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

State: Active specification with bounded implementation shipped behind `CANVAS_ENABLED`. Session logs, in-place body editing, governance-routing, and API/CLI session lifecycle landed via PRs #605/#618/#619/#626; owner-doc promotion now records the surface as materially supported while hybrid Panel/Chat behavior remains future work. Phase 5 (durable chat artifact, closing D-4 on epic #2778) shipped through #2806 / PR #2873 and #2807 / PR #3486.
Owner: v6.0 architecture owner
Last reviewed: 2026-07-02

# Canvas Chat Surface

## What This Capability Builds

A user opens a note in the vault and starts a canvas session. The agent edits the note body directly, in place, as they collaborate — the way a second author would. The user does not review a diff; they see edits appear. The session closes. The note retains the result. A session log in `.chats/<note-slug>/` captures the intent trail.

Each applied co-authoring request appends one session-log turn containing the user's intent and the
change summary for that body edit. The session log is subordinate provenance, not a second durable
source of note content.

This is the human flow described in `docs/HUMAN-FLOWS.md` §8: "I want to think on a note with a writing partner."

## What This Capability Does Not Build

- A general-purpose UI or editor library, and no production hosting decision (Obsidian, standalone, web). **Scope note:** Phase 1 (the four tasks below) builds no UI. Phase 2 ("Agentic Canvas Co-Authoring", further below) narrows this exclusion: it adds a *bounded* Companion UI co-authoring surface in the dev/staging shell — not a general editor library and not a production hosting decision, both of which remain deferred.
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

## Phase 2 — Agentic Canvas Co-Authoring

Phase 1 (above) built the session lifecycle, the body-writer path, the governance gate, and the
session API. It did **not** build the agent: `CanvasWriter.apply_edit` still requires a
caller-supplied `new_body`, and `read_only_cognition.py` is execution-denied and unwired. So
co-authoring with an agent editing in place is not yet reachable. Phase 2 closes that gap as a
bounded vertical slice and is **Agentic Lab** (opt-in, gated behind `CANVAS_ENABLED`; it does not
change Core Runtime defaults).

| Order | Task File | Issue | What It Builds | Parallelizable |
|-------|-----------|-------|----------------|----------------|
| 1 | [GENERATE_COAUTHORING_EDIT.md](GENERATE_COAUTHORING_EDIT.md) | #1716 (`agent:ready`) | Write-capable co-authoring cognition + `POST /coauthor` applying generated body via CanvasWriter | — |
| 2 | [SURFACE_CANVAS_IN_COMPANION_UI.md](SURFACE_CANVAS_IN_COMPANION_UI.md) | #1717 (`agent:blocked` on #1716) | Canvas surface in the Companion UI shell: intent input, applied-edit render, undo, session lifecycle | depends on 1 |

```
GENERATE_COAUTHORING_EDIT
        ↓
SURFACE_CANVAS_IN_COMPANION_UI
```

Phase 2 acceptance (validated on parent feature issue #1715 — **delivered**, closed 2026-06-09):

- [x] A user intent during an active session produces an agent-generated body edit applied in place.
- [x] Frontmatter/cross-note generations route through the gated pipeline, never applied as co-authoring.
- [x] The Companion UI shell makes the loop reachable (intent → applied edit → undo) behind `CANVAS_ENABLED`.
- [x] Core Runtime defaults and the read-only Chat scaffold are unchanged.
- [x] `docs/STATUS.md` records the Phase 2 delivery receipt (PR #1724).

## Phase 3 — Chat→Panel Governance Handoff

**Delivered (dev/staging, 2026-06-09).** Phase 2 made co-authoring reachable and routed
governance-bearing generations to the Panel pipeline server-side, but the handoff was previously
dead-ended in the UI (`_route_governance_bearing` discarded the `intent_id` and raised an opaque
409). Phase 3 made the crossing navigable end to end, per
`docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` (Agentic Lab, gated
behind `CANVAS_ENABLED`; Panel stays the primary command surface; receipts stay server-owned). One
follow-up remains: wiring the served dev page to invoke `/coauthor` in live JS (#1733).

| Order | Task File | Issue | What It Builds | Status |
|-------|-----------|-------|----------------|--------|
| 1 | [RETURN_GOVERNANCE_HANDOFF_REFERENCE.md](RETURN_GOVERNANCE_HANDOFF_REFERENCE.md) | #1726 (PR #1731) | API returns a structured handoff reference (`intent_id`/`action_type`/`status`); staged proposal marked proposal-scoped `proposal_origin="canvas_coauthoring"` | `closed` |
| 2 | [SURFACE_CHAT_TO_PANEL_HANDOFF.md](SURFACE_CHAT_TO_PANEL_HANDOFF.md) | #1727 (PR #1732) | Canvas region links to the staged proposal; Panel rail shows canvas origin; confirm via existing flow | `closed` |
| 3 | [REFLECT_HANDOFF_RECEIPT.md](REFLECT_HANDOFF_RECEIPT.md) | #1728 (PR #1734) | Executed receipt reflected back into the canvas/originating context (read-only, server-declared) | `closed` |

Follow-up: #1733 — wire the live `serve_dev_page` co-authoring flow to call `/coauthor` and render the handoff affordance (delivered, PR #1736).

Live operator UAT script for the full Phase 2 + Phase 3 loop: `docs/runbooks/UAT_CANVAS_COAUTHORING.md`.

```
RETURN_GOVERNANCE_HANDOFF_REFERENCE
        ↓
SURFACE_CHAT_TO_PANEL_HANDOFF
        ↓
REFLECT_HANDOFF_RECEIPT
```

Phase 3 parent feature issue: **#1725** — validation hub (**delivered**; closed 2026-06-09).

Phase 3 acceptance (validated on parent feature issue #1725 — **delivered**):

- [x] A governance-bearing co-authoring intent returns a handoff reference correlating it to a Panel proposal.
- [x] The Companion UI links the canvas intent to the canvas-originated Panel proposal and confirms via the existing Panel flow.
- [x] The executed receipt is reflected back into the originating context, read-only and server-declared.
- [x] Panel remains the primary command surface; the gated-execution invariant and "receipts not invented" hold.
- [x] `docs/STATUS.md` records the Phase 3 delivery receipt (PR #1735).

Phase 2 parent feature issue: **#1715** — live validation hub; closes only after the dev-shell demo passes and the `docs/STATUS.md` Companion UI claim is promoted.

## Phase 4 — Intent-level governance classification on `/coauthor`

**Delivered (dev/staging, 2026-06-09).** Phase 3 made the Chat→Panel handoff navigable, but
`/coauthor` still decided whether a mutation was governance-bearing only by inspecting the *generated
body* for a frontmatter block — the "known limitation" recorded in
`docs/runbooks/UAT_CANVAS_COAUTHORING.md` §4. Phase 4 closes that gap: `/coauthor` now classifies
the **intent** with an LLM-backed `IntentClassifierCognition` before any body is generated.
Governance-bearing natural-language intents (e.g. "promote this note to evergreen") route to the
gated Panel pipeline with the correct `GovernanceActionType` — the note is never touched. Exploratory
intents return a non-mutating read-only response. Co-authoring intents and a degraded classifier fall
through to the existing generate-and-apply path unchanged. The body-frontmatter check is kept as
defense-in-depth. Agentic Lab, gated behind `CANVAS_ENABLED`; Core Runtime defaults unchanged.

| Order | Task File | Issue | What It Builds | Status |
|-------|-----------|-------|----------------|--------|
| 1 | [CLASSIFY_COAUTHORING_INTENT.md](CLASSIFY_COAUTHORING_INTENT.md) | #1743 (PR #1747) | LLM-backed `IntentClassifierCognition` labeling intent as co-authoring / governance-bearing / exploratory (+ `GovernanceActionType`); conservative degraded default; pure, no mutation | `closed` |
| 2 | [ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR.md](ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR.md) | #1744 (PR #1754) | Wire classifier into `POST /coauthor`: governance-bearing intents route to Panel with the classified action_type before generation; body-frontmatter check kept as backstop; runbook + README closure bundled | `closed` |

```
CLASSIFY_COAUTHORING_INTENT
        ↓
ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR
```

Phase 4 parent feature issue: **#1742** — validation hub (closed after both child slices delivered).

Phase 4 acceptance (validated on the parent feature issue — **delivered**):

- [x] A natural-language governance intent through `/coauthor` routes to the gated Panel pipeline with the correct `action_type`, body unchanged, no body generated.
- [x] Co-authoring intents still generate and apply in place; exploratory intents are read-only and never mutate the note.
- [x] A degraded/unavailable classifier falls through to the existing behavior (no regression, no fabricated routing); the body-frontmatter backstop remains.
- [x] The gated-execution invariant and Panel-as-primary-command-surface posture hold; Core Runtime defaults unchanged.
- [x] The UAT runbook §4 "Known limitation" note is replaced with a deterministic natural-language routing walkthrough.

## Phase 5 — Durable Chat Artifact (D-4 closure)

Epic #2778 ratified D-4 (`docs/architecture/runtime-semantics.md` class 19): chat becomes its own
artifact class, carrying a relationship to the note it belongs to (note 1 : N chats). Phases 1–4 above
already built the chat-session artifact and its one-to-many note relationship
(`DEFINE_CANVAS_COEDITING_MODEL.md`) — what was missing was formal identity/canonicality/GC semantics,
an SBS ownership statement, a registered relation type, and a WriteGuard-gated write path (today
`SessionLogWriter` writes raw files, the one durable HKA-adjacent artifact in this system that bypasses
WriteGuard). Phase 5 closes that gap by **extending** the existing contract, not replacing it — see
`DEFINE_CHAT_ARTIFACT_DURABILITY.md :: Reconciliation` for the explicit statement that this does not
reopen the note-is-the-artifact / session-is-provenance split.

| Order | Task File | What It Builds | Lane | Parallelizable |
|-------|-----------|----------------|------|-----------------|
| 1 | [DEFINE_CHAT_ARTIFACT_DURABILITY.md](DEFINE_CHAT_ARTIFACT_DURABILITY.md) | Identity/canonicality/GC classification, SBS conformance statement, `chat_for`/`has_chats` relation-taxonomy entry, SBS mapping-register row | docs-authoring | — |
| 2 | [PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md](PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md) | WriteGuard-gated, KnowledgePort-routed chat-session writes; durable `note_uuid` field; rename-safe `load_chat_sessions_for_note` query | implementation | depends on 1 |

```
DEFINE_CHAT_ARTIFACT_DURABILITY
        ↓
PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD
```

## Cross-Task Invariants / Interaction Safety (Phase 5)

Phase 5 has exactly one runtime-state-writing task (Task 2); Task 1 is docs-only. The two tasks
share one piece of state across the seam: the `note_uuid` field name and its `chat_for`/`has_chats`
relation semantics, defined in Task 1 and consumed by Task 2's implementation.

- **Invariant.** The `note_uuid` frontmatter field is the durable source of the note↔chat
  relationship; its registration in `RELATION_TAXONOMY.md` (Task 1) is documentation/discoverability,
  never a runtime precondition for the field to function.
- **Delivered ordering.** Task 1 merged first through #2806 / PR #2873; Task 2 then merged through
  #2807 / PR #3486. `note_uuid` remains the direct durable relation at runtime; the taxonomy is
  documentation/discoverability, not a runtime lookup precondition.
- **No seam risk to note content.** Neither task's failure mode, in either order, touches the vault
  note's own content or frontmatter — the invariant that content authority stays with the note
  (see `DEFINE_CHAT_ARTIFACT_DURABILITY.md :: Reconciliation`) holds regardless of Phase 5's internal
  sequencing.

Phase 5 acceptance (verified 2026-08-12):

- [x] `chat_for`/`has_chats` are registered in `docs/CONCEPTS/RELATION_TAXONOMY.md` (#2806 / PR #2873).
- [x] `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` carries a session/chat-history row
      (#2806 / PR #2873).
- [x] Chat-session writes (`open_session`/`append_turn`/`close_session`) assert WriteGuard at the
      production call site and route through KnowledgePort (#2807 / PR #3486).
- [x] Chat-session artifacts carry a durable `note_uuid` field, resolved via `ensure_note_uuid`
      (#2807 / PR #3486).
- [x] `load_chat_sessions_for_note` finds a note's sessions by `note_uuid`, surviving a note rename
      (#2807 / PR #3486).
- [x] No Phase 1–4 canvas behavior regresses: `pytest -q tests/chat
      tests/companion_ui/test_canvas_*.py tests/api/test_canvas*.py` passed (367 passed, 2026-08-12).
- [x] `docs/architecture/runtime-semantics.md` D-4 is ratified (PR #2803, merged 2026-07-02), naming
      the artifact class as "HKA-owned like class 1/3, related 1:N to its parent vault note via SIP" —
      consistent with this phase's classification.

Phase 5 parent feature issue: **#2805** — validation hub; its children are delivered and this
checklist is complete. The parent closes after this current-state documentation update merges.

### Carried governance intent in routed proposal payloads (#1772)

Routed governance handoffs no longer stage an empty proposal payload. Both routing paths on
`/coauthor` thread the original natural-language request into the staged Panel proposal
(`PanelActionMapping.params` on the proposal's action, and quoted in the proposal's human-facing
instruction), so Panel review shows what the human actually asked for:

- **Intent-classifier path** — payload carries `original_request`, `routed_via: "intent_classifier"`,
  `intent_class`, `classified_action_type`, and the classifier rationale when one was produced.
- **Defense-in-depth backstop path** (`GovernanceBearingMutationError` branches) — no classified
  fields exist, so the payload carries `original_request` and
  `routed_via: "body_frontmatter_backstop"` only; backstop payloads never fabricate classifier
  fields.

Authority is unchanged: the carried payload is proposal-class context for human review/execution.
Nothing auto-executes from intent text — WriteGuard and the explicit `POST /api/panel/confirm`
confirmation path are untouched, and the explicit `/governance` endpoint continues to pass the
caller-supplied payload through unchanged.
