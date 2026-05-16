---
name: Name The Three Interaction Surfaces
description: Establish Panel, Chat, and Automation as three distinct interaction surfaces with their own cognitive postures, and explain why they are not collapsible
task_id: INTERACTION-01
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 10A
parent_capability: Interaction surfaces and authority boundaries
prerequisites: []
depends_on: []
can_parallelize_with: [DEFINE_PANEL_AUTHORITY_BOUNDARY, DEFINE_CHAT_AUTHORITY_BOUNDARY, DEFINE_AUTOMATION_SURFACE_AUTHORITY, STATE_EXECUTION_AUTHORITY_REMAINS_GATED]
---

State: Specification draft. Docs-only. Foundation for the rest of the capability.

# Name The Three Interaction Surfaces

## Purpose

Create the shared vocabulary for the rest of the capability. Name Panel, Chat, and Automation as three distinct interaction surfaces, give each one a cognitive posture, and explain why they cannot be collapsed into a single conversation surface or a single authority lane.

Without this task, the other task files drift into incompatible language (for example, treating "automation" as "everything non-Panel" or treating Chat and Panel as two flavors of the same surface).

## What This Task Does

Produces a single docs section that:

1. Names exactly three interaction surfaces: **Panel**, **Chat**, **Automation**.
2. For each surface, states its cognitive posture in one sentence:
   - Panel — artifact-intent oriented: agent-surfaced likely intention, human confirmation, governed action, local receipt.
   - Chat — exploration-oriented: externalize and manipulate thought, reason across context, optionally commit through governance.
   - Automation — proactive or scheduled: the system acts on the user's behalf without a live interactive turn, within a governed and inspectable envelope.
3. States why the three are not collapsible:
   - Different cognitive postures (command, exploration, proactive).
   - Different authority envelopes (see sibling tasks).
   - Different accountability surfaces (Panel receipts live in-note; automation receipts live in event/outbox history; Chat receipts — if canvas-Chat mutates — would live somewhere named by the reconcile task).
   - Different failure modes (Panel can mis-parse intent; Chat can over-reason; Automation can over-act).
4. States explicitly what this task does not do: it does not decide the Chat mutation question; it does not describe a Chat implementation; it does not change Panel runtime truth; it does not reclassify any current runtime behavior.
5. Ties the three surfaces back to the user-needs model: Panel serves "make an explicit move on the vault," Chat serves "externalize and manipulate thought," Automation serves "the system does the small stuff for me without asking."

## Concretely

The deliverable is a section inside this task file titled `## The Three Surfaces` that lists Panel, Chat, and Automation with the fields above, plus a short note on what "collapsible" would look like and why the architecture rejects it.

Example of the non-collapsibility argument shape (not the finished text — the finished version will be drafted during implementation review):

- If Panel and Chat were collapsed into "one conversation surface", the user would lose the ability to know which posture they are in and would lose the receipt locality that Panel currently provides via in-note status callouts.
- If Chat and Automation were collapsed, "the system reasoned about something" and "the system acted on something" would share an authority lane, breaking the gated-execution invariant named in `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.
- If Panel and Automation were collapsed, every scheduled or watcher-driven action would inherit Panel's explicit-intent framing, making proactive behavior look interactive when it is not.

## Why This Matters

The rest of the capability — defining each surface's authority boundary and reconciling the Chat mutation question — assumes this three-way split. If the split is fuzzy, the reconcile task cannot frame the Chat contradiction sharply, because "Chat" would mean different things to different readers.

This task also protects against a common failure mode in dual-interaction designs: one surface silently absorbs the other. v6.0 Pillar 10A exists precisely to prevent that absorption.

## Acceptance Criteria

- [x] The task file names exactly three surfaces: Panel, Chat, Automation.
- [x] Each surface has a one-sentence cognitive posture statement. Panel: artifact-intent oriented (updated from command-oriented per issue #1019).
- [x] The non-collapsibility argument explicitly covers all three pairwise collisions (Panel/Chat, Chat/Automation, Panel/Automation).
- [x] The task file does not describe any Chat implementation detail.
- [x] The task file does not answer the Chat mutation question; it defers to `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- [x] The task file references `docs/plans/V60_ARCHITECTURE_TARGET.md` Pillar 10A as its source anchor.
- [x] The vocabulary used here is reused verbatim in `DEFINE_PANEL_AUTHORITY_BOUNDARY.md`, `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`, and `DEFINE_AUTOMATION_SURFACE_AUTHORITY.md`.

## How to Verify (Pre-Merge)

Docs review only:

- A reviewer unfamiliar with v6.0 can read this file and name the three surfaces and their cognitive postures in their own words.
- A grep across the other task files shows consistent naming (Panel, Chat, Automation — not "conversation surface," "bot surface," "agent surface," or similar drift).
- The file contains no runtime commands, no code references, no schema changes.

## Out of Scope

- Defining each surface's mutation authority in detail (handled by the three sibling authority tasks).
- Deciding the Chat mutation question (handled by `RECONCILE_CHAT_MUTATION_AUTHORITY.md`).
- Describing how automation is currently implemented (watcher, scheduler) beyond the posture statement.
- Recommending or rejecting any future surface beyond these three.
- Reclassifying any current v5.x runtime behavior.

## The Three Surfaces

The system provides three distinct interaction surfaces — **Panel**, **Chat**, and **Automation** — each serving different user cognitive postures and working within separate authority boundaries.

### Panel: Artifact-Intent Oriented Surface

**Cognitive posture:** artifact-intent oriented — agent-surfaced likely intention, human confirmation, governed action, local receipt.

Panel is the artifact-local surface where the agent may manifest what it believes the user likely wants to do with the current artifact, and the user recognizes, corrects, or confirms that interpretation before anything changes. The user need not have fully formulated the intention before Panel surfaces it. Panel helps the user discover and decide what should happen with the active artifact — its likely next move, role, classification, lifecycle, follow-up, or governed action.

Panel does not externalize open-ended thought like Chat/Canvas. It externalizes a bounded, artifact-local hypothesis about what the user may want to do with this specific artifact next. This keeps the Panel/Chat separation sharp rather than weakening it.

The interaction posture is: artifact state → agent proposes likely intention → user recognizes/corrects/confirms → confirmed intention enters governed execution → receipt is written near the artifact.

Panel is therefore **proposal-oriented before confirmation** and **command/receipt-oriented at the execution boundary**. Explicit intent may emerge after the agent manifests a likely next action and the user confirms it — rather than always originating as a fully-formed user command.

Panel serves the user need for **preserving authorship and control** — the user remains the decision-maker, and every confirmed action is traceable and reversible.

### Chat: Exploration-Oriented Surface

**Cognitive posture:** externalize and manipulate thought, reason across context, optionally commit through governance.

Chat is a reasoning and exploration surface where the user can externalize incomplete thoughts, ask questions, develop ideas, and have the system reason with them about the vault. Chat can draw on broader context, offer possibilities, and help the user think through decisions — but Chat is not a commitment surface. If Chat reasoning leads to a durable change, that change must be committed through Panel or an explicit Chat-to-Vault submission gate that enforces governance rules.

Chat serves the user need for **thinking outside the head** and **recovering orientation** — the user gets reasoning support, context synthesis, and idea development without the finality of direct modification.

### Automation: Proactive-or-Scheduled Surface

**Cognitive posture:** proactive or scheduled; the system acts on the user's behalf without a live interactive turn, within a governed and inspectable envelope.

Automation is where the system acts unilaterally on behalf of the user based on rules, schedules, or watcher-driven triggers — but only within a pre-authorized governance envelope. The user does not initiate each action, but the system remains inspectable: what actions happened, why, and with what results remain visible in the system's receipt and trace surfaces.

Automation serves the user need for **managing commitments without mental overload** — the system handles the small stuff automatically while preserving the user's ability to understand and correct what it did.

### Why These Three Cannot Collapse

#### Panel and Chat Cannot Collapse

Panel and Chat serve categorically different cognitive functions:

- **Chat/Canvas externalizes open-ended thought** and supports co-authoring within or around the artifact's content — text work, idea development, reasoning across context.
- **Panel externalizes bounded artifact-local likely intention** — what the agent hypothesizes the user may want to do with this artifact as a system artifact (its next move, role, classification, lifecycle, follow-up, or governed action).

Panel is not a co-authoring surface. Panel is not a generic conversation surface. Panel is not a Canvas Suggestion Flow variant. The surfaces may coexist but cannot substitute for each other.

If Panel and Chat were unified into a single "conversation surface," the user would lose:
- the distinction between thinking aloud (Chat) and deciding what should happen to an artifact (Panel),
- the local receipt mechanism that Panel provides via in-note status callouts,
- and the ability to reason exploratively without those thoughts being treated as artifact lifecycle decisions.

Semantically, Panel is artifact-decision-oriented and Chat is thought-externalization-oriented. Combining them would blur which cognitive mode the user is in and erode the artifact-local accountability that Panel provides.

#### Chat and Automation Cannot Collapse

If Chat and Automation shared one interaction lane, the system would blur "something the system reasoned about" and "something the system acted on." This violates the gated-execution invariant (see `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`): reasoning and cognition are safe to share widely, but unilateral action must remain authorized and bounded. Automation executes with pre-authorized scope; Chat does not. Merging them would either make Chat dangerously permissive or make Automation unnecessarily interactive.

#### Panel and Automation Cannot Collapse

If Panel and Automation were unified, every scheduled or watcher-driven action would inherit Panel's framing of explicit interactive intent. This makes asynchronous, rule-driven system behavior appear interactive when it is not. The user's cognitive model would be wrong: they would expect the receipt, confirmation, and presence of interaction that Panel promises, but Automation cannot guarantee.

### What This Task Does Not Do

This task:
- **does not decide the Chat mutation question.** That belongs to `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- **does not describe a Chat implementation.** Implementation details belong to later tasks.
- **does not change Panel runtime truth.** The current Panel behavior stands; this task only names and formalizes the semantic.
- **does not reclassify any current runtime behavior.** Current v5.x watcher/automation/agent behavior remains as-is; this task describes the wanted-state semantic framework.
- **does not recommend whether more than three surfaces should exist.** The architecture commits to these three; future expansion is out of scope.

### Grounding in User Needs

These three surfaces align with distinct user needs:
- **Panel** supports "discover and decide what should happen with the active artifact" and "make a confirmed move on the vault" (user need #8: preserving authorship and control).
- **Chat** supports "externalize and manipulate thought" (user need #2: thinking outside the head).
- **Automation** supports "the system does the small stuff without asking" (user need #4: managing commitments without mental overload).

Together, they give the user three different cognitive modes within one coherent system, each with its own authority boundary and accountability surface.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10, §Pillar 10A
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model
- `docs/DESIGN_PRINCIPLES.md` §2A Interaction-First Architecture
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/ROADMAP.md` §Interaction Model Evolution

## Related GitHub Issues

This capability does not create GitHub issues. If this task later maps to an implementation issue, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES" and use the acceptance criteria above as the issue contract.

---

**Status:** Specification draft. Completed. Ready for review.
