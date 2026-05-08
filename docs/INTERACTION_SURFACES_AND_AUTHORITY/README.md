---
name: Interaction Surfaces and Authority Specification
description: System specification for naming interaction surfaces (Panel, Chat, Automation), their authority boundaries, and how cognition crosses between them safely
type: specification
authority: SoT for interaction-surface authority boundaries and the Chat mutation reconciliation decision
source_of_truth:
  - docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 10 / Pillar 10A
  - docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Fixed Decisions + Interaction Model
  - docs/DESIGN_PRINCIPLES.md :: Boundary-First / Interaction-First / Explicit Mutation Authority / Governance Before Autonomy
related_docs:
  - docs/ROADMAP.md :: Interaction Model Evolution + Capability-Based Architecture
  - docs/PANEL_AGENT.md
  - docs/CONCEPTS/USER_NEEDS_MODEL.md
  - docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md
  - docs/HUMAN-FLOWS.md
---

State: Active specification for v6.0 capability "Interaction surfaces and authority boundaries". The specification itself remains docs-first; downstream implementation issues and runtime slices may reference it without making canvas Chat or Chat-originated mutation current runtime behavior.

# Interaction Surfaces and Authority Specification

This directory is the system specification for one v6.0 capability: making explicit what each interaction surface in the system is, what authority it carries on the user's behalf, and how richer cognition can cross between surfaces without collapsing their different roles.

Each task file is a discrete docs-only specification. Each task is independently reviewable and mergeable. Tasks describe intent, acceptance criteria, verification surfaces, and what the task does not do. These are not issue templates; one task spec may later map to one or many GitHub issues.

See [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) for the capability-level acceptance contract.

## Human needs this serves

Grounded in `docs/CONCEPTS/USER_NEEDS_MODEL.md` and the cognitive-prosthetic framing in `docs/DESIGN_PRINCIPLES.md`:

- **Externalize and manipulate thought.** The user needs a surface where thinking can be laid down, rearranged, and recombined without that activity silently mutating durable state. "Chat as canvas" is the named shape of this need.
- **Trust what the system did on my behalf.** Every surface that can change the vault, the graph, or scheduled behavior must have a legible authority boundary so the user can inspect, reverse, and accept-or-reject changes.
- **Know which surface I am in and what it can do.** The user should be able to describe, in one sentence per surface, what that surface is allowed to do on their behalf and why, and that sentence should match what the docs say.

The capability serves these needs by making surfaces, their authority, and the crossings between them explicit in docs first, before any runtime work tries to bind them.

## What this capability is NOT

This capability specification deliberately excludes several things that would be parallel-unsafe or premature:

- **Not building a Chat surface.** No front-end, no route, no websocket, no agent wiring. This is docs-only authoring.
- **Not implementing Deep Agents.** Deep Agent rollout has its own v6.0 lane. This spec only names the authority envelope a Deep Agent would have to fit into.
- **Not changing Panel runtime.** PanelAgent code, event schemas, intent pipelines, and note-writer paths are untouched. The spec describes Panel's current authority boundary; it does not redesign it.
- **Not changing automation behavior.** Watcher, scheduled jobs, proactive agents keep their current runtime semantics. The spec names the authority lane they already occupy.
- **Not implementing Chat mutation.** The spec records the Chat read-only-vs-canvas decision, but it does not build Chat, change Panel, or authorize any runtime mutation path outside the governed execution pipeline.
- **Not editing DOCS_INDEX.md, V60_CAPABILITY_AND_AGENT_EVOLUTION.md, DESIGN_PRINCIPLES.md, or any file outside this directory.** The reconciliation task may recommend edits to other docs; it does not make them.

## The Chat contradiction this spec must address

There was a live contradiction in the v6.0 doc surface:

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions says Chat is "the safer Deep Agent entry surface because it is read-only."
- The same document, later in §Interaction Model, softens this: Chat "Starts read-only. ... May later participate in governed mutation paths, but that should be a later architecture decision rather than an early assumption."
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority explicitly permits multiple governed mutation paths: "The architecture may include multiple governed mutation paths; the design goal is governed mutation, not necessarily one exclusive mutation surface."
- The user's stable intent, carried in long-running design memory, treats Chat as a canvas-like thinking surface — meaning Chat can externalize thought and carry governed mutation rights that are not identical to Panel's command-oriented mutation authority.

The recorded resolution is Candidate A: `docs/DESIGN_PRINCIPLES.md` is the higher-authority contract. "Read-only" applies to the Deep Agent introduction phase, not to Chat's identity. Chat is a canvas-shaped surface that may later carry governed mutation rights through the gated execution pipeline.

`RECONCILE_CHAT_MUTATION_AUTHORITY.md` is the task file that records this decision. Every other task file should read its `## Decision` section as authoritative for the Chat mutation question.

Crucially, "Chat as canvas" is not a revival of the ASK-style question-answering loop. ASK was receive-query / return-answer. Canvas is externalize-thought / manipulate-in-place / optionally commit-through-governance. The spec must keep these two framings distinct so no task accidentally reintroduces ASK semantics under a new name.

## Reading order

1. [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) — capability-level context, scope, constraints, acceptance.
2. [NAME_THE_THREE_INTERACTION_SURFACES.md](NAME_THE_THREE_INTERACTION_SURFACES.md) — the three surfaces and why they are not collapsible.
3. [DEFINE_PANEL_AUTHORITY_BOUNDARY.md](DEFINE_PANEL_AUTHORITY_BOUNDARY.md) — Panel's current authority and mutation path.
4. [CHAT_FAMILY_TAXONOMY.md](CHAT_FAMILY_TAXONOMY.md) — names the chat-family interaction surfaces (Panel command dialogue, Canvas co-authoring, Retrieval dialogue, Workspace synthesis, Operator console) and the modularity requirement that prevents collapse into a generic chat product.
5. [DEFINE_CHAT_AUTHORITY_BOUNDARY.md](DEFINE_CHAT_AUTHORITY_BOUNDARY.md) — Chat as canvas-shaped thinking surface, with future mutation constrained by the recorded Candidate A decision.
6. [DEFINE_AUTOMATION_SURFACE_AUTHORITY.md](DEFINE_AUTOMATION_SURFACE_AUTHORITY.md) — Automation as a distinct authority lane.
7. [RECONCILE_CHAT_MUTATION_AUTHORITY.md](RECONCILE_CHAT_MUTATION_AUTHORITY.md) — the keystone decision task.
8. [STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md](STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md) — the invariant that no surface mutates durable state without governance.
9. [DEFINE_CANVAS_COEDITING_MODEL.md](DEFINE_CANVAS_COEDITING_MODEL.md) — the co-editing posture, co-authoring vs governance-bearing split, note-as-artifact / session-as-provenance, `.chats/` and `type:` conventions.
10. [DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md](DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md) — compatibility note that Panel is the primary command-oriented surface, not the exclusive authoritative intent surface.
11. [HYBRID_CHAT_INTEGRATION_SCHEMA.md](HYBRID_CHAT_INTEGRATION_SCHEMA.md) — docs-only schema for how canvas Chat integrates with Panel, session provenance, and governed execution without becoming a second Panel.

Tasks 2, 3, 4, 5, and 7 may proceed in parallel as docs drafts. Task 6 (reconcile) depends on tasks 2–5 naming the surfaces consistently and on task 7 stating the gated-execution invariant, because the reconcile task evaluates options against those contracts.

## Capability-level acceptance criteria

The capability "Interaction surfaces and authority boundaries" is accepted when:

- [ ] Each of Panel, Chat, and Automation has a one-sentence authority statement that the user can read and agree with, and that sentence appears in the relevant task spec.
- [ ] The three surfaces are described with consistent vocabulary across all task files in this directory.
- [ ] The Chat contradiction is explicitly named in `RECONCILE_CHAT_MUTATION_AUTHORITY.md`, with: evaluation criteria, decision owner, two named candidate resolutions (DESIGN_PRINCIPLES wins / V60 plan wins), and an acceptance condition on what "decided" means.
- [ ] `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` states the invariant that no interaction surface (including any canvas-Chat) mutates durable state without passing through policy / validation / event-pipeline governance, and that LLM reasoning alone never triggers execution.
- [ ] The spec reflects the recorded Candidate A resolution without claiming any current Chat runtime implementation.
- [ ] The spec does not reintroduce ASK-style Q&A semantics under the "canvas" label.
- [ ] No files outside `docs/INTERACTION_SURFACES_AND_AUTHORITY/` are modified by this capability.
- [ ] Any hybrid Chat/Panel integration preserves the command-vs-canvas distinction and routes governance-bearing mutations through the same gated execution boundary.

Owner-doc promotion (updates to `docs/DESIGN_PRINCIPLES.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, `docs/ROADMAP.md`, or `docs/PANEL_AGENT.md`) is separate from this specification and must remain truthful about current runtime behavior.

## Relationship to GitHub issues

This directory is the source of truth. GitHub issues that implement or validate downstream slices reference task specs with "Implements INTERACTION_SURFACES_AND_AUTHORITY/{TASK_NAME}" and use the task's acceptance criteria as the issue contract. Creating those issues does not by itself promote future canvas Chat or Chat-originated mutation into current runtime behavior.

## Navigation

- Parent plan: `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10, §Pillar 10A
- Working plan: `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions, §Interaction Model
- Design contract: `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority, §Interaction-First Architecture
- Roadmap alignment: `docs/ROADMAP.md` §Interaction Model Evolution, §Capability-Based Architecture
- Current Panel truth: `docs/PANEL_AGENT.md`
- User needs: `docs/CONCEPTS/USER_NEEDS_MODEL.md`

---

**Status:** Specification active. Chat mutation reconciliation is resolved as Candidate A; runtime Chat implementation and canvas-commit receipt shape remain future capability work.
