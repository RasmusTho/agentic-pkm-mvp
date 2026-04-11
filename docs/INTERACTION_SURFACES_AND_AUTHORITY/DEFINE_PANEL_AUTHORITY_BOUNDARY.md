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
   Proposed authority statement (to be finalized during review): "Panel is the command-oriented interaction surface where the user expresses explicit intent inside a vault note, and the system translates that intent into governed, receipt-bearing actions through the intent/event/note-writer pipeline."

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
   Command-oriented. The user sees the action, checks it, and is accountable for it. Panel does not externalize thinking; it executes committed intent.

5. **Panel's receipt surface.**
   In-note AI status callout plus event stream (`panel.intent.created`, `panel.intent.executed`, downstream intents). Panel's receipts live where the action happened, which is a key part of why the user can trust what the system did.

6. **Panel's relationship to cognition.**
   Panel may consume richer cognition in the future (Phase 3 of the V60 plan) but only as planning and proposal support. Cognition does not become authority inside Panel.

## Concretely

The deliverable is a section in this file titled `## Panel Authority Boundary` that captures the six points above, plus a short "what a reviewer should be able to say out loud after reading this" paragraph.

Example of the one-sentence test the task must pass: a reviewer reading the section should be able to say "Panel turns explicit in-note checkboxes into governed events and writes a receipt back into the same note" without looking at runtime code.

## Why This Matters

Panel is currently the only shipping mutation-capable interaction surface. If its authority envelope is fuzzy, the rest of the capability has nothing to compare against when deciding what Chat or Automation should or should not do. More importantly, Panel's receipt locality (receipts live in the note the action happened in) is a trust feature the other surfaces must either match or differ from deliberately — not by accident.

## Acceptance Criteria

- [ ] The task file contains a one-sentence Panel authority statement.
- [ ] The "is allowed" list is grounded in `docs/PANEL_AGENT.md` Runtime V1 and does not invent capabilities.
- [ ] The "is not allowed" list explicitly includes "no LLM reasoning alone triggers mutation" and references `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` for the invariant.
- [ ] Panel's cognitive posture language matches the vocabulary established in `NAME_THE_THREE_INTERACTION_SURFACES.md`.
- [ ] The receipt surface section names in-note status callout and the event stream.
- [ ] The task file does not propose changes to Panel runtime, schemas, or events.
- [ ] The task file explicitly says this is current truth, not a redesign.

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

## Related GitHub Issues

None in this capability. If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY" and use the acceptance criteria above.

---

**Status:** Specification draft. No blockers.
