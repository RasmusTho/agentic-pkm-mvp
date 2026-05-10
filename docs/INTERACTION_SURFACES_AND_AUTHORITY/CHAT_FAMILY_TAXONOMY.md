---
name: Chat-Family Interaction Taxonomy
description: Docs-only taxonomy that names the chat-family interaction surfaces in this system, distinguishes their authority/persistence/cognitive roles, and prevents collapse into a single generic chat product
type: specification
authority: SoT for naming and bounding chat-family interaction surfaces; subordinate to DEFINE_CHAT_AUTHORITY_BOUNDARY.md and STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md for authority semantics
related_docs:
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md
  - docs/CANVAS_CHAT_SURFACE/README.md
  - docs/HUMAN-FLOWS.md
---

State: Active docs-only specification. Names the chat-family taxonomy; does not introduce new runtime behavior. Canvas Chat remains gated behind `CANVAS_ENABLED`; all other chat-family surfaces described here are either current Panel behavior, current operator surfaces, or explicitly future capability work.

# Chat-Family Interaction Taxonomy

## Why this taxonomy exists

"Chat" is **not a single architectural primitive in this system.** It is a family of dialogue-like or conversational interaction affordances that look superficially similar — line-oriented, turn-shaped, often LLM-mediated — but differ sharply in:

- **Authority** — what each surface is allowed to do on the user's behalf.
- **Persistence** — what is durable, what is provenance, and what is ephemeral.
- **Cognitive role** — the human need each surface serves (command, co-authoring, recall, synthesis, operator inspection).

Treating these as one surface produces predictable failures: ASK-style Q&A creeps back into the architectural center, the Panel command surface gets diluted, durable meaning gets stranded in transcripts, and governance-bearing mutations slip past the gated execution boundary. This document names the family members so future work cannot collapse them by accident.

This taxonomy is subordinate to:

- [DEFINE_CHAT_AUTHORITY_BOUNDARY.md](DEFINE_CHAT_AUTHORITY_BOUNDARY.md) — "Chat is canvas, not ASK."
- [DEFINE_CANVAS_COEDITING_MODEL.md](DEFINE_CANVAS_COEDITING_MODEL.md) — note-as-artifact / session-as-provenance.
- [STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md](STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md) — gated-execution invariant.

If anything in this taxonomy appears to contradict those, the other documents win.

## Family members

### A. Panel command dialogue

- **Shape:** Command-oriented, note-local, turn-shaped exchanges between user and PanelAgent inside the active note.
- **Use:** Intent clarification, proposed actions, explicit commands, receipts, confirmations.
- **Authority:** Panel remains the **primary command-oriented surface**. Governance-bearing actions originating in Panel route through the gated execution boundary (policy / validation / event pipeline). LLM reasoning in Panel does not by itself trigger execution.
- **Persistence:** Receipts and command outcomes are durable in the note; the conversational scaffolding around them is provenance, not source of truth.
- **Status:** Current runtime behavior.

### B. Canvas co-authoring session

- **Shape:** Canvas-shaped, note-first, user-present co-authoring of the currently open note.
- **Use:** Externalize and manipulate thought in place; the user and the system co-edit the body of one note while the user is present.
- **Authority:** Body edits to the currently open note may apply directly during an active session, authorized by user presence. Governance-bearing mutations (anything beyond the active note's body, or anything affecting graph/scheduled/system artifacts) remain gated.
- **Persistence:** **The note is the durable artifact.** The `.chats/` session log is **subordinate provenance**, not source of truth. Promotion of session content into durable meaning happens explicitly, not by transcript accumulation.
- **Status:** Materially implemented behind `CANVAS_ENABLED`. Hybrid Panel/Chat behavior remains future work.

### C. Retrieval dialogue

- **Shape:** ASK/RAG-like source-grounded inquiry — receive question, return answer with citations.
- **Use:** Retrieval, orientation, question answering, source-backed recall over the existing vault and indexed sources.
- **Authority:** **Read-only by default.** This surface must not become the architectural center again (see `docs/FINDING_AND_REORIENTING/DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md`). If a retrieval dialogue ever needs to mutate durable state, it escalates to a governed mutation path; it does not gain mutation authority by virtue of being conversational.
- **Persistence:** Answers cite sources; the dialogue itself is ephemeral or provenance-only. Citations preserve provenance back to the source notes.
- **Status:** Conceptually allowed as a bounded surface; not the system's center. Any current ASK-shaped affordance is constrained to this role.

### D. Workspace synthesis session

- **Shape:** Multi-note or multi-source synthesis, reconciliation, and drafting across the workspace.
- **Use:** Cross-note reasoning, reconciliation of overlapping notes, drafting new artifacts that integrate multiple existing ones.
- **Authority:** Distinct from single-note canvas co-authoring. **Cross-note writes are governance-bearing by definition** and must route through the gated execution boundary; user presence in one note does not authorize edits to others.
- **Persistence:** Outputs land in explicit artifacts (new notes, receipts, governed system artifacts), not in a workspace-wide transcript.
- **Status:** **Future capability / not current runtime.** Listed here so future work does not silently fold it into Canvas co-authoring or into a generic chat product.

### E. Operator / agent console

- **Shape:** Developer/operator surface — CLI, Codex, Claude Code, runtime diagnostics, agent execution inspection. Often visually conversational.
- **Use:** Building, debugging, operating, and inspecting the system itself.
- **Authority:** Acts under operator/developer privileges, not end-user PKM cognition. Must not be promoted into the primary human-facing PKM chat surface; the operator surface and the user-facing cognitive surface are different products even if they share LLM mediation.
- **Persistence:** Logs, transcripts, and agent traces are operator artifacts, not user-facing durable meaning.
- **Status:** Current operator/dev tooling. Out of scope for the cognitive-prosthetic UX surface.

## Comparison

| Surface | Primary human need | Interaction shape | Persistence model | Mutation authority | Current status |
| --- | --- | --- | --- | --- | --- |
| A. Panel command dialogue | Issue commands, see what the system did on my behalf | Command-oriented, turn-shaped, note-local | Receipts durable in note; conversation is provenance | Primary command surface; mutations gated through governed execution | Current runtime |
| B. Canvas co-authoring session | Externalize and manipulate thought with the system in the note I'm in | Canvas-shaped, note-first, user-present | Note is the artifact; `.chats/` session log is subordinate provenance | Body edits to active note authorized by presence; cross-boundary mutations gated | Behind `CANVAS_ENABLED`; hybrid behavior future |
| C. Retrieval dialogue | Find and orient against what the vault already knows | Source-grounded Q&A with citations | Ephemeral or provenance-only; citations preserve source links | Read-only by default; mutation requires escalation to a governed path | Bounded role only; not the architectural center |
| D. Workspace synthesis session | Reconcile and synthesize across many notes/sources | Multi-source drafting and reconciliation | Outputs land in explicit artifacts, not a workspace transcript | Cross-note writes governance-bearing; gated by definition | Future capability |
| E. Operator / agent console | Build, debug, and operate the system | Conversational developer/operator interface | Logs and traces as operator artifacts | Operator/developer privilege; not end-user authority | Current dev tooling |

## Shared rules across the chat family

These rules apply to every member of the family. They are restatements of existing contracts, scoped to chat-family surfaces.

1. **No chat transcript becomes the semantic source of truth by default.** Durable meaning belongs in notes, explicit artifacts, receipts, or governed system artifacts — not in transcripts.
2. **Session logs are provenance, not authority.** Promotion of session content into durable meaning is a separate, governed step; transcript accumulation never silently promotes itself.
3. **Governance-bearing mutation always uses the gated execution boundary.** No chat-family surface mutates durable state outside the active-note body of a present user without passing through policy / validation / event-pipeline governance. LLM reasoning alone never triggers execution. (See `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.)
4. **Retrieval/source-grounded dialogue must preserve provenance.** Citations and source links are not optional decoration; they are how the read-only contract is honored.
5. **The surfaces must not collapse into one generic chat product.** Panel, Canvas, Retrieval, Workspace, and Operator have different authority, persistence, and cognitive roles. They may share UI primitives but must not share authority or persistence contracts.
6. **No surface inherits authority from another by visual similarity.** A surface that looks like Panel does not gain Panel's command authority; a surface that looks like Canvas does not gain co-authoring write rights.

## Modularity requirement

The chat family must be implemented as **replaceable components, not as one monolithic chat product.**

- **Shared UI primitives are allowed.** Message bubbles, input affordances, citation chips, streaming indicators, code blocks, and similar rendering/input components may be reused across surfaces.
- **Surface-specific contracts must remain behind clear interfaces.** Authority, persistence, retrieval, and mutation contracts belong to the surface, not to the shared components. A reused message bubble does not import authority from the surface it was last used in.
- **The taxonomy must support swapping** frontend components, agent runtimes, retrieval providers, event-stream protocols, and persistence adapters **without changing the semantic role of each surface.** If swapping the LLM provider or the streaming transport requires re-deciding what Canvas means, the abstraction is wrong.
- **Do not couple the taxonomy to specific tech.** This document and the surfaces it names must not be coupled to any single UI library, agent harness, LLM provider, retrieval stack, or persistence format beyond the already-authoritative vault/session/receipt contracts. Naming a vendor in passing is fine; binding a surface's identity to a vendor is not.

> **Companion UI principle.** The Companion UI should be modular by construction: shared rendering/input components may be reused across Panel command dialogue, Canvas co-authoring, Retrieval dialogue, Workspace synthesis, and Operator console, but each surface must bind to its own authority and persistence adapter so components can be replaced without changing system semantics.

## Implications for future UI implementation

- A future Companion UI **may host multiple chat-family surfaces** — possibly all of A–E in different views, modes, or panels. The taxonomy is the contract that keeps them distinct inside one shell.
- **UI components may be shared across surfaces, but authority and persistence contracts must remain separate.** Each surface binds to its own authority adapter (what it is allowed to do) and its own persistence adapter (where its durable artifacts live and what is provenance).
- **Generic OSS chat applications such as Open WebUI or LibreChat should not be imported as the primary foundation** of the Companion UI. Their conversation-first, transcript-as-product model conflicts directly with this taxonomy: it would re-promote the transcript to source of truth, blur Panel's command role into a generic chat field, and drag ASK-shaped semantics back into the architectural center.
- **OSS libraries and references are still useful as UI primitives or pattern references** — message rendering, streaming, markdown, citation UX patterns — provided they do **not** own persistence, memory, retrieval, or mutation authority. Use them for pixels, not for product shape.

## What this document is NOT

- Not a runtime change. No code is being introduced or modified by this file.
- Not a claim that Workspace synthesis exists today; it is named as a future surface so it is not retrofitted into Canvas.
- Not a re-opening of the Chat mutation reconciliation; Candidate A in `RECONCILE_CHAT_MUTATION_AUTHORITY.md` stands.
- Not a license for Retrieval dialogue to grow mutation rights; read-only-by-default is binding.
- Not a UI design document. It constrains UI work without specifying it.

## Related docs

- [docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md](README.md)
- [docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md](DEFINE_CANVAS_COEDITING_MODEL.md)
- [docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md](HYBRID_CHAT_INTEGRATION_SCHEMA.md)
- [docs/CANVAS_CHAT_SURFACE/README.md](../CANVAS_CHAT_SURFACE/README.md)
- [docs/HUMAN-FLOWS.md](../HUMAN-FLOWS.md)
