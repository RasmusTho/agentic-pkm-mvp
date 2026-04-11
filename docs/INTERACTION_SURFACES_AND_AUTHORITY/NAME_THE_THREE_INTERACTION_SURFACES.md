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
   - Panel — command-oriented: explicit intent, explicit action, explicit receipt.
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

- [ ] The task file names exactly three surfaces: Panel, Chat, Automation.
- [ ] Each surface has a one-sentence cognitive posture statement.
- [ ] The non-collapsibility argument explicitly covers all three pairwise collisions (Panel/Chat, Chat/Automation, Panel/Automation).
- [ ] The task file does not describe any Chat implementation detail.
- [ ] The task file does not answer the Chat mutation question; it defers to `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- [ ] The task file references `docs/plans/V60_ARCHITECTURE_TARGET.md` Pillar 10A as its source anchor.
- [ ] The vocabulary used here is reused verbatim in `DEFINE_PANEL_AUTHORITY_BOUNDARY.md`, `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`, and `DEFINE_AUTOMATION_SURFACE_AUTHORITY.md`.

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

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10, §Pillar 10A
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model
- `docs/DESIGN_PRINCIPLES.md` §2A Interaction-First Architecture
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/ROADMAP.md` §Interaction Model Evolution

## Related GitHub Issues

This capability does not create GitHub issues. If this task later maps to an implementation issue, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES" and use the acceptance criteria above as the issue contract.

---

**Status:** Specification draft. No blockers.
