---
name: Interaction surfaces and authority boundaries for Panel, Chat, and automation
description: Parent feature issue body for the v6.0 capability that names Panel, Chat, and Automation as distinct interaction surfaces with explicit authority boundaries and reconciles the Chat read-only-vs-canvas contradiction
type: parent-feature-issue
authority: Capability-level contract; not yet filed as a GitHub issue
parent_capability: Interaction surfaces and authority boundaries
source_anchors:
  - docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 10, Pillar 10A
  - docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Fixed Decisions, Interaction Model
  - docs/DESIGN_PRINCIPLES.md :: Boundary-First, Interaction-First, Explicit Mutation Authority, Governance Before Autonomy
  - docs/ROADMAP.md :: Interaction Model Evolution, Capability-Based Architecture
---

# [Feature] Interaction surfaces and authority boundaries for Panel, Chat, and automation

## Context

The v6.0 architecture target treats Panel and Chat as distinct interaction surfaces with different authority boundaries (`docs/plans/V60_ARCHITECTURE_TARGET.md` Pillar 10A). The capability working plan and the roadmap both echo this, but carry an unresolved contradiction about Chat.

The contradiction, stated plainly:

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions calls Chat "the safer Deep Agent entry surface because it is read-only."
- The same doc's §Interaction Model softens this: Chat "Starts read-only. ... May later participate in governed mutation paths, but that should be a later architecture decision rather than an early assumption."
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority already permits multiple governed mutation paths and states that the design goal is governed mutation, not a single exclusive mutation surface.
- The product intent, held consistently in long-running design memory, treats Chat as a canvas-like thinking surface: a place to externalize, manipulate, and optionally commit thought through governed paths. Canvas is not the same as ASK-style query-answer Q&A.

There is no single sentence in docs today that a new contributor can read to know what each interaction surface is allowed to do on the user's behalf. This capability fixes that for Panel, Chat, and Automation, and surfaces the Chat mutation question as a bounded, owned decision.

The Automation lane (watchers, scheduled jobs, proactive agents) is a third surface that is already live in the runtime but is under-described in the interaction model. Naming it explicitly avoids collapsing "anything non-Panel" into Chat.

## Scope

In scope:

- Name the three interaction surfaces: Panel, Chat, Automation.
- For each surface, write a one-sentence authority statement, a cognitive posture description, and an explicit list of what the surface is and is not allowed to do on the user's behalf today.
- State the invariant that no interaction surface mutates durable state except through the existing governed path (policy, validation, event pipeline, note writer).
- Reframe "Chat is read-only" as applying specifically to the Deep Agent introduction phase, not to Chat's identity, and surface the broader Chat mutation question as a named, bounded, owned design decision.
- Keep ASK-style receive-query / return-answer semantics out of the Chat definition. Canvas is externalize-and-manipulate, not Q&A.

Out of scope in this capability (handled separately or deferred):

- Building any Chat surface implementation.
- Introducing Deep Agents into any surface.
- Changing PanelAgent code, events, or pipelines.
- Editing `docs/DESIGN_PRINCIPLES.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, `docs/plans/V60_ARCHITECTURE_TARGET.md`, `docs/ROADMAP.md`, or `docs/PANEL_AGENT.md`. The reconcile task may recommend edits, but the edits belong to a follow-up owner-doc promotion PR.
- Changing `docs/DOCS_INDEX.md`.
- Creating GitHub issues. This capability stops at specification.

## Source Anchors

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10 — Surface, authority, and accountability distinctions stay explicit.
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10A — Interaction surfaces stay separate from cognition and execution.
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions — "Deep Agents start in Chat before Panel"; "System-of-systems framing"; "Execution remains gated".
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model — Panel and Chat section definitions.
- `docs/DESIGN_PRINCIPLES.md` §4 Explicit Mutation Authority — "may include multiple governed mutation paths".
- `docs/DESIGN_PRINCIPLES.md` §2A Interaction-First Architecture — interaction is primary, authority is part of the primary model.
- `docs/DESIGN_PRINCIPLES.md` §5 Governance Before Autonomy — read-only cognition precedes mutation-capable autonomy.
- `docs/ROADMAP.md` §Interaction Model Evolution and §Capability-Based Architecture.
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` — externalize thought, trust what the system did, know which surface I am in.

## Constraints

- Docs-only. No runtime code, no schemas, no tests changed.
- No GitHub issues created by this capability.
- No files outside `docs/INTERACTION_SURFACES_AND_AUTHORITY/` are modified.
- The reconcile task must surface the Chat mutation question, not close it. The capability is acceptable whether the decision later resolves in favor of DESIGN_PRINCIPLES or in favor of the V60 plan's "read-only" framing.
- "Canvas" must be specified in contrast to, not as a revival of, the ASK-style Q&A loop.
- All task files must use the feature-breakdown skill's frontmatter and section shape.

## Acceptance Criteria

- [ ] Specification directory exists at `docs/INTERACTION_SURFACES_AND_AUTHORITY/` with README and six task files.
- [ ] Each of Panel, Chat, and Automation has a one-sentence authority statement that the user can read, and that sentence is present verbatim in the relevant task spec.
- [ ] The three surfaces are described with consistent vocabulary across every task file.
- [ ] `RECONCILE_CHAT_MUTATION_AUTHORITY.md` explicitly names the Chat mutation question, lists at least two candidate resolutions (DESIGN_PRINCIPLES wins; V60 plan wins), names a decision owner slot, and sets an acceptance condition for what "decided" means.
- [ ] `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` states the gated-execution invariant and makes it explicit that LLM reasoning alone never triggers execution.
- [ ] The spec does not pre-empt the reconcile decision.
- [ ] The spec does not reintroduce ASK-style Q&A semantics under the canvas framing.
- [ ] A reviewer can describe, in one sentence per surface, what that surface is allowed to do on the user's behalf, using only the docs in this directory.

## Out of Scope

- Any runtime or schema change.
- Any change to `docs/DESIGN_PRINCIPLES.md`, `docs/plans/V60_*`, `docs/ROADMAP.md`, `docs/PANEL_AGENT.md`, or `docs/DOCS_INDEX.md`.
- Building, wiring, or prototyping a Chat surface.
- Introducing, selecting, or scoping Deep Agents.
- Deciding the Chat mutation question.
- Creating GitHub issues or project items.

## Suggested Validation

1. A reviewer who has not read the v6.0 plan reads `README.md` plus the six task files and can name the three surfaces, their authority boundary, and the open Chat question in their own words.
2. The reviewer can articulate why canvas-Chat is not ASK-Q&A.
3. The reviewer can point to exactly one file that owns the Chat mutation decision.
4. `git diff` shows no changes outside `docs/INTERACTION_SURFACES_AND_AUTHORITY/`.

## Source Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/DESIGN_PRINCIPLES.md`
- `docs/ROADMAP.md`
- `docs/PANEL_AGENT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` (if present, for vocabulary alignment)
- `docs/HUMAN-FLOWS.md` (interaction-related flows)

## Implementation Tasks

The specification directory is [docs/INTERACTION_SURFACES_AND_AUTHORITY/](.). Tasks, in reading order:

1. [NAME_THE_THREE_INTERACTION_SURFACES.md](NAME_THE_THREE_INTERACTION_SURFACES.md)
2. [DEFINE_PANEL_AUTHORITY_BOUNDARY.md](DEFINE_PANEL_AUTHORITY_BOUNDARY.md)
3. [DEFINE_CHAT_AUTHORITY_BOUNDARY.md](DEFINE_CHAT_AUTHORITY_BOUNDARY.md)
4. [DEFINE_AUTOMATION_SURFACE_AUTHORITY.md](DEFINE_AUTOMATION_SURFACE_AUTHORITY.md)
5. [RECONCILE_CHAT_MUTATION_AUTHORITY.md](RECONCILE_CHAT_MUTATION_AUTHORITY.md)
6. [STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md](STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md)

Execution order: tasks 1–4 and 6 can proceed in parallel as docs drafts. Task 5 (reconcile) depends on tasks 1–4 having landed a consistent vocabulary and task 6 having stated the gated-execution invariant.

## Verification Path

Per-task verification is docs review:

- Each task file has the required frontmatter and section shape.
- Each task file stays inside `docs/INTERACTION_SURFACES_AND_AUTHORITY/`.
- Each task file cites at least one source anchor listed above.
- No task file presumes a resolution to the Chat mutation question.
- `RECONCILE_CHAT_MUTATION_AUTHORITY.md` specifies: contradiction, criteria, candidates, decision owner slot, acceptance condition.

## Validation / Acceptance Path

The capability is validated when:

1. A reviewer familiar with v6.0 reads only this directory and can describe the three surfaces' authority boundaries and the open Chat question in their own words, without consulting anything else.
2. A second reviewer, coming from the product-intent side, confirms that Chat-as-canvas is preserved as a live possibility and that ASK-style Q&A is not reintroduced under a new label.
3. The reconcile task is either (a) closed by a recorded decision naming which resolution wins, or (b) held open as a named, owned, bounded design decision with an explicit deadline or blocking condition. Either outcome is acceptable capability acceptance; pre-empting the decision inside the spec is not acceptable.
4. Any follow-up owner-doc promotion (edits to `docs/DESIGN_PRINCIPLES.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, etc.) is handled by a separate, later capability, not by this one.

---

**Status:** Parent feature issue body drafted. Not yet filed on GitHub. Filing is explicitly deferred per the capability's docs-only scope.
