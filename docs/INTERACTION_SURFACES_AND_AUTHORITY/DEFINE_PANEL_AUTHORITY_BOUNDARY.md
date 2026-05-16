---
name: Define Panel Authority Boundary
description: State what Panel is allowed to do on the user's behalf, its current mutation path, and its relationship to intent and action governance
task_id: INTERACTION-02
source_anchor: docs/PANEL_AGENT.md :: Runtime V1 (fan-out, promotion intent, receipts)
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01]
depends_on: [NAME_THE_THREE_INTERACTION_SURFACES.md]
can_parallelize_with: [DEFINE_CHAT_AUTHORITY_BOUNDARY, DEFINE_AUTOMATION_SURFACE_AUTHORITY, STATE_EXECUTION_AUTHORITY_REMAINS_GATED]
---

State: Specification draft. Docs-only. Reflects current runtime truth; does not redesign Panel.

# Define Panel Authority Boundary

## Purpose

Make Panel's authority boundary legible in one place: what it is, what it can change on the user's behalf, what it cannot, and how its mutation path is already governed.

Panel is the runtime baseline for mutation-capable interaction in v5.5 and v6.0. This task does not redesign Panel. It documents the already-shipped contract so the other tasks — and especially `RECONCILE_CHAT_MUTATION_AUTHORITY.md` — can compare against a stable reference.

## What This Task Does

Produces a docs section that states:

1. **What Panel is, in one sentence.**
   Authority statement: "Panel is the artifact-local intent manifestation and confirmation surface where the agent may propose likely next actions for the active artifact, the user recognizes/corrects/confirms intent, and confirmed intent enters governed, receipt-bearing execution through the intent/event/note-writer pipeline."

2. **What Panel is allowed to do on the user's behalf, today.**
   - Parse checked panel actions into `panel.intent.created` events.
   - Emit `panel.intent.executed` with per-action status.
   - Emit downstream intents such as `promote.intent.created`.
   - Remove executed checkboxes from the panel working set and write an in-note receipt callout.
   - Mutate note frontmatter via the note writer path (never directly).

3. **What Panel is not allowed to do.**
   - Mutate durable state outside the note writer / event pipeline path.
   - Act on unchecked or ambiguous panel items without surfacing them as suggested checkboxes.
   - Use LLM reasoning as the sole basis for a mutation; every mutation flows through policy + validation + the deterministic writer path.
   - Carry forward intent across notes without an explicit new panel action.

4. **Panel's cognitive posture.**
   Artifact-intent oriented. The agent surfaces likely next intentions; the user recognizes, corrects, or confirms them. Panel does not externalize open-ended thought like Chat/Canvas; it externalizes a bounded, artifact-local interpretation of what the user may want to do next. Panel is proposal-oriented before confirmation and command/receipt-oriented at the execution boundary.

5. **Panel's receipt surface.**
   In-note AI status callout plus event stream (`panel.intent.created`, `panel.intent.executed`, downstream intents). Panel's receipts live where the action happened, which is a key part of why the user can trust what the system did.

6. **Panel's relationship to cognition.**
   Panel may consume richer cognition in the future (Phase 3 of the V60 plan) but only as planning and proposal support. Cognition does not become authority inside Panel.

## Concretely

The deliverable is a section in this file titled `## Panel Authority Boundary` that captures the six points above, plus a short "what a reviewer should be able to say out loud after reading this" paragraph.

Example of the one-sentence test the task must pass: a reviewer reading the section should be able to say "Panel surfaces likely artifact intentions as proposals; the user confirms; confirmed intent enters governed execution and a receipt is written back into the same note" without looking at runtime code.

## Why This Matters

Panel is currently the only shipping mutation-capable interaction surface. If its authority envelope is fuzzy, the rest of the capability has nothing to compare against when deciding what Chat or Automation should or should not do. More importantly, Panel's receipt locality (receipts live in the note the action happened in) is a trust feature the other surfaces must either match or differ from deliberately — not by accident.

## Acceptance Criteria

- [x] The task file contains a one-sentence Panel authority statement.
- [x] The "is allowed" list is grounded in `docs/PANEL_AGENT.md` Runtime V1 and does not invent capabilities.
- [x] The "is not allowed" list explicitly includes "no LLM reasoning alone triggers mutation" and references `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` for the invariant.
- [x] Panel's cognitive posture language matches the vocabulary established in `NAME_THE_THREE_INTERACTION_SURFACES.md`.
- [x] The receipt surface section names in-note status callout and the event stream.
- [x] The task file does not propose changes to Panel runtime, schemas, or events.
- [x] The task file explicitly says this is current truth, not a redesign.

## How to Verify (Pre-Merge)

Docs review:

- The claims in this file can be checked against `docs/PANEL_AGENT.md` line-by-line.
- No claim exceeds what `docs/PANEL_AGENT.md` already states.
- A reviewer can map each bullet in "is allowed" to a specific runtime behavior listed in `docs/PANEL_AGENT.md` §Runtime V1.
- The file contains no implementation or schema changes.

## Out of Scope

- Redesigning Panel.
- Changing event payloads.
- Extending Panel to new intents or actions.
- Describing PanelAgent 2.0 or LangGraph decider mechanics beyond citing them as the current runtime.
- Deciding whether Chat's authority should match, exceed, or stay narrower than Panel's.

## Related Docs

- `docs/PANEL_AGENT.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model §Panel
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority
- `docs/ROADMAP.md` §Panel Agent rollup
- Sibling: `NAME_THE_THREE_INTERACTION_SURFACES.md`
- Sibling: `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`
- Sibling: `DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md`
- Sibling: `HYBRID_CHAT_INTEGRATION_SCHEMA.md`

## Related GitHub Issues

None in this capability. If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY" and use the acceptance criteria above.

---

## Panel Authority Boundary

**This section captures current runtime truth. It does not redesign Panel.**

### One-Sentence Authority Statement

Panel is the artifact-local intent manifestation and confirmation surface where the agent may propose likely next actions for the active artifact, the user recognizes/corrects/confirms intent, and confirmed intent enters governed, receipt-bearing execution through the intent/event/note-writer pipeline.

### What Panel Is Allowed to Do on the User's Behalf Today

Grounded in `docs/PANEL_AGENT.md` §Runtime V1:

- Parse checked panel action checkboxes into `panel.intent.created` events.
- Emit `panel.intent.executed` with per-action status (success, failure, or logged/unhandled).
- Emit `panel.action.triggered` for handled actions and `panel.action.logged` for unmapped or unhandled actions.
- Emit downstream intents such as `promote.intent.created` when a checked action carries `intent_type: promotion`.
- Remove executed checkboxes from the panel working set on re-run.
- Write an in-note AI status callout receipt (`> [!info]- AI status`) that records outcomes via the note writer path.
- Mutate note frontmatter via the note writer / event pipeline path — never directly.
- Surface uncertain or no-checkbox interpretations as suggested unchecked checkboxes so ambiguous intent stays human-reviewable before entering the execution path.

### What Panel Is Not Allowed to Do

- Mutate durable state outside the note writer / event pipeline path.
- Act on unchecked or ambiguous panel items without first surfacing them as suggested checkboxes for explicit human confirmation.
- Use LLM reasoning as the sole basis for a mutation; every mutation flows through policy, validation, and the deterministic writer path. See `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` for the invariant that governs this constraint.
- Carry forward intent across notes without an explicit new panel action on the target note.
- Execute actions the user has not explicitly checked, except for freeform catalog-driven proposals that are written back as suggested (unchecked) checkboxes first.

### Panel's Cognitive Posture

**Artifact-intent oriented.**

Panel does not externalize open-ended thought like Chat/Canvas. Instead, it externalizes the agent's bounded interpretation of what the user may want to do with this specific artifact next.

The interaction posture is:

```
artifact state -> agent proposes likely intention -> user recognizes/corrects/confirms -> confirmed intention enters governed execution -> receipt is written near the artifact.
```

Panel is therefore **proposal-oriented before confirmation** and **command/receipt-oriented at the execution boundary**.

This posture is consistent with the vocabulary in `NAME_THE_THREE_INTERACTION_SURFACES.md`. The user sees proposed actions, decides whether to confirm them, and is accountable for confirmed actions. The key shift from a purely command-oriented framing: the user may not have fully formulated the intention before Panel surfaces it. Panel makes likely artifact intentions visible so the user can recognize, correct, or confirm them — rather than requiring the user to initiate a fully-formed command.

### Panel's Receipt Surface

- **In-note AI status callout** (`> [!info]- AI status`): foldable, lives in the note where the action happened, trimmed to the last 20 entries.
- **Event stream**: `panel.intent.created`, `panel.intent.executed`, `panel.action.triggered`, `panel.action.logged`, and downstream events such as `promote.intent.created`.

Receipt locality is a deliberate trust feature: receipts live where the action happened, making Panel's side effects directly observable without leaving the note context. The other interaction surfaces must either match this locality or differ from it deliberately — not by accident.

### Panel's Relationship to Cognition

Panel currently uses LLM reasoning (`PANEL_AGENT_DECIDER=llm` is the default runtime posture) to interpret panel instructions and select catalog-matching actions. This cognition is bounded to action selection. Cognition does not become authority: no LLM output triggers a mutation unless the user has confirmed a checked checkbox or the freeform path has written back a suggested checkbox for human review first.

Panel may consume richer cognition in the future (v6.0 Phase 3) but only as planning and proposal support. The mutation authority boundary does not change when cognition is added.

### What a Reviewer Should Be Able to Say After Reading This

"Panel is the artifact-local surface where the agent surfaces likely next intentions as reviewable proposals. The user recognizes, corrects, or confirms those proposals. Only confirmed intent enters the governed execution path: policy, WriteGuard, deterministic note-writer, and receipt. LLM reasoning informs action selection and proposal generation, but does not bypass human confirmation for mutations."

Panel is the primary command-oriented surface, not the exclusive authoritative intent surface. Hybrid Chat integration must preserve Panel's receipt-bearing command role while allowing Chat-originated governance-bearing intents to enter the same gated execution boundary when explicitly authorized.

---

**Status:** Specification draft. No blockers.
