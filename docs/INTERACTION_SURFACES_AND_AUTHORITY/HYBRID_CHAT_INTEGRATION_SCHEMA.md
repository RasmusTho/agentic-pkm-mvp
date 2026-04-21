---
name: Hybrid Chat Integration Schema
description: Define the docs-only integration contract between canvas Chat, Panel's governed command path, session provenance, and future hybrid interaction flows
task_id: INTERACTION-09
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md :: Authority Split
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-02, INTERACTION-03, INTERACTION-06, INTERACTION-07, INTERACTION-08]
depends_on:
  - DEFINE_PANEL_AUTHORITY_BOUNDARY.md
  - DEFINE_CHAT_AUTHORITY_BOUNDARY.md
  - RECONCILE_CHAT_MUTATION_AUTHORITY.md
  - STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md
  - DEFINE_CANVAS_COEDITING_MODEL.md
  - DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md
can_parallelize_with: []
---

State: Compatibility schema. Docs-only. Names future integration boundaries; does not implement Chat, change Panel runtime, add events, change schemas, or alter persistence.
Doc role: Spec
Authority: Compatibility schema for reading future hybrid Panel/Chat designs against the existing interaction-surface authority contracts.
Owner: v6.0 architecture owner
Last reviewed: 2026-04-21
Last verified against: docs/ARCHITECTURE.md, DEFINE_PANEL_AUTHORITY_BOUNDARY.md, DEFINE_CHAT_AUTHORITY_BOUNDARY.md, RECONCILE_CHAT_MUTATION_AUTHORITY.md, STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md, DEFINE_CANVAS_COEDITING_MODEL.md, DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md

# Hybrid Chat Integration Schema

## Purpose

Define how a future hybrid Chat implementation should connect canvas co-authoring, session provenance, and governed execution without collapsing Panel and Chat into the same surface.

This is a schema for docs and design review, not a runtime schema. It names the expected boundaries so later implementation issues can be sliced without reopening the authority decision already recorded in `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.

## Compatibility Rule

Panel and Chat are both valid user-intent surfaces. Their distinction is interaction structure, not whether intent is authoritative:

- Panel is the primary command-oriented surface.
- Chat is the canvas/co-authoring surface.
- Governance-bearing mutations from either surface use the gated execution boundary.
- Content co-authoring inside the currently open note during an active Chat session is authorized by user presence and audited by session provenance.

"Hybrid" means the surfaces can hand work across boundaries. It does not mean they become one surface.

## Integration Surfaces

Hybrid integration has four named surfaces:

1. **Canvas session.** The active Chat/co-authoring context where the user and assistant work on a note body.
2. **Session provenance.** The subordinate `.chats/` artifact that records intent, prompts, and change summaries for the active session.
3. **Governed execution boundary.** The policy, validation, event, and note-writer path used for governance-bearing mutations.
4. **Panel command locality.** The in-note command/receipt posture that remains Panel's shipped runtime role and the reference locality for governed action receipts.

These surfaces may exchange references, but each keeps its own authority class.

## Allowed Crossings

The following crossings are compatible with the existing contracts:

- Chat session to session provenance: append the active session's prompts and change summaries.
- Chat session to note body: apply in-place co-authoring edits to the currently open note during an active user-present session.
- Chat session to governed execution boundary: submit a governance-bearing intent for policy and validation.
- Governed execution boundary to Panel command locality: emit or display receipts using the same locality as existing Panel-governed mutation receipts.
- Panel command locality to Chat session: open or reference a Chat session as context for a command, without letting Panel inherit Chat's canvas semantics.

## Disallowed Crossings

The following crossings are not compatible:

- Chat directly mutates frontmatter classification, cross-note state, note lifecycle state, or system artifacts without governed execution.
- Panel becomes a long-lived canvas transcript or co-authoring workspace.
- Session provenance becomes the canonical note or competes with the note as the durable artifact.
- Chat-originated governance-bearing receipts live only inside a chat transcript with no governed execution trace.
- Panel's "primary command surface" role is interpreted as excluding Chat-originated user intent.

## Intent Classes

Hybrid integration should preserve three intent classes:

### Co-authoring intent

User-present intent to edit the body of the currently open note during an active session.

Authority:
- authorized by user presence,
- bounded to the note body,
- reversible by undo,
- audited by session provenance.

### Governance-bearing intent

Intent to change classification, metadata with policy meaning, multiple notes, note lifecycle, promotion/commitment state, or system-owned artifacts.

Authority:
- must pass through policy and validation,
- must use the event/note-writer path,
- must produce a receipt outside the transient chat transcript.

### Exploratory intent

Intent to reason, compare, plan, draft, or orient without mutating durable state.

Authority:
- may use richer cognition,
- may prepare candidate changes,
- does not itself authorize durable mutation.

## Minimum Future Runtime Questions

Before implementation, a future issue must answer:

- How does a Chat session identify the currently open note?
- How does the system know a user-present co-authoring session is active?
- What is the append-only session provenance shape beyond the minimum fields in `DEFINE_CANVAS_COEDITING_MODEL.md`?
- How does a Chat-originated governance-bearing intent enter the existing execution boundary?
- Where does the user inspect the receipt for a Chat-originated governance-bearing mutation?
- What is the rollback path for co-authored text versus governed execution side effects?

This document deliberately does not answer those implementation questions.

## Acceptance Criteria

- [ ] Hybrid designs preserve Panel as primary command-oriented surface without making it the exclusive authoritative intent surface.
- [ ] Hybrid designs preserve Chat as canvas/co-authoring surface without making it an unrestricted execution path.
- [ ] Co-authoring, governance-bearing, and exploratory intent remain distinct.
- [ ] Governance-bearing mutations from Chat route through the same gated execution boundary as Panel-originated mutations.
- [ ] Session provenance remains subordinate to the note artifact.
- [ ] No runtime, schema, event, or persistence change is implied by this docs-only schema.

## Related Docs

- `docs/ARCHITECTURE.md` §Interaction Surfaces
- `DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md`
- `DEFINE_PANEL_AUTHORITY_BOUNDARY.md`
- `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`
- `DEFINE_CANVAS_COEDITING_MODEL.md`
- `RECONCILE_CHAT_MUTATION_AUTHORITY.md`
- `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`

---

**Status:** Compatibility schema. Runtime implementation remains future work.
