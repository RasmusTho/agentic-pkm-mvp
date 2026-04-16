---
name: Define Commitment vs Execution Plan
description: Explicit contract separating commitments (what the user owes or is waiting on) from execution plans (how the system orders its own work)
task_id: COMMITMENT-FIRST-CLASS-03
source_anchor: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Relation to execution artifacts
parent_capability: Commitments as a first-class semantic family
prerequisites: [COMMITMENT-FIRST-CLASS-01]
depends_on: [NAME_THE_COMMITMENT_FAMILY.md]
can_parallelize_with: [DEFINE_COMMITMENT_VS_NOTE_STATE, DEFINE_COMMITMENT_STATE_TRANSITIONS, DEFINE_COMMITMENT_RECEIPT_REQUIREMENT]
---

State: Specification for the commitment vs execution-plan boundary in the v6.0 commitment-first-class capability. Docs-only.

# Define Commitment vs Execution Plan

## Purpose

This task draws the explicit boundary between a commitment (what the user owes, is waiting on, or considers next) and an execution plan (the ordered steps the system takes to do system work). It exists because the second most dangerous flattening — after collapsing commitments into note state — is to treat a planner/orchestrator `Plan` as if it were the user's authoritative project or next-action structure. When that happens, the runtime's sequencing of tool calls silently becomes the representation of the user's responsibilities, and the user loses the ability to recognize what they owe independently of what the system decided to do.

## What This Task Does

Write three contract sections in this file:

1. "## What an execution plan is" — a short pointer to the execution-artifact vocabulary used in the repo today (`Plan`, `Subplan`, planner/orchestrator step, tool-call sequence). This is a pointer, not a redefinition.
2. "## What a commitment is, and why it is not a plan" — the explicit contract: a commitment is a **human responsibility structure** expressed in user-facing terms ("I owe", "I'm waiting on", "this is what's next for me"); an execution plan is a **system process structure** expressed in runtime terms ("these are the steps the orchestrator will take"). They are related but must not share vocabulary.
3. "## Forbidden vocabulary collisions" — a concrete list of terms that must NOT be reused across the two layers in the v6 architecture.

The forbidden-vocabulary section must name at least:

- `Plan` as execution-only; a commitment is never called a `Plan`.
- `Step` as execution-only; a `Next Action` is never called a `Step`.
- `waiting` meaning a commitment state must not be reused for "orchestrator awaiting tool result".
- `done` meaning a commitment is closed must not be reused for "execution step finished".
- `next` meaning the user's `Next Action` must not be reused for "next orchestrator step".
- `project` must not be reused for "planner project" or "execution project".

The contract must also include a "direction of causality" statement: execution plans may SUPPORT commitment work (the system can generate a plan to help advance a project), but generating an execution plan does not create a commitment, and closing an execution plan does not close a commitment. The human's commitment landscape is authoritative over runtime plans, not the other way around.

## Concretely

When complete, a reader can decide correctly whether any given statement belongs on the commitment layer or the execution layer. Examples:

- "I need to reply to Alice by Friday." → `Commitment` / `Waiting` / `Next Action`. NOT a plan step.
- "The orchestrator will call the summarizer, then the retriever, then the writer." → execution plan. NOT a commitment.
- "The user's weekly review is due." → `Review Cycle`. NOT a scheduled runtime job.
- "The system generated a draft plan to help the user move the hiring project forward." → execution artifact that SUPPORTS a `Project` commitment. The plan does not replace the commitment; the commitment existed before the plan and continues to exist after the plan finishes.

The contract must also state: if the runtime generates a plan and the plan completes, this does NOT automatically transition any commitment to `done`. Commitment transitions belong to the user's decision (possibly assisted by the system), not to runtime plan completion.

## Why This Matters

The user's trust in cognitive offloading depends on commitments being their own thing, recognizably user-owned, and not secretly redefined by whatever the orchestrator did last. If a finished execution plan can silently close a commitment, the user will stop trusting the system to track responsibility. The user will start keeping their open loops somewhere else — on paper, in their head, in another app — because the system is behaving like an automation log rather than a second brain.

Concretely, collapsing commitments into execution plans causes these failure modes:

- The orchestrator finishes a plan; the user's `Project` commitment is marked done by mistake; the user loses track of what they actually still owe.
- The user asks "what's next on this project?"; the system answers with the next planner step instead of the next human next action; the user receives a tool-call name instead of a responsibility.
- The runtime cannot generate a plan for a commitment yet; the commitment disappears from view because the UI is plan-shaped rather than commitment-shaped.

Each of these turns the system from a cognitive prosthetic into an automation log. The contract in this file exists to prevent that at the architecture layer.

## What an execution plan is

An execution plan (called `Plan`, `Subplan`, or execution structure in the runtime vocabulary) is a generated system artifact used to sequence and coordinate work that the system performs.

The authoritative vocabulary for execution artifacts is documented in:
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (§Execution Artifact)
- `docs/ARCHITECTURE.md` (execution and planner sections)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (execution-layer evolution)

Execution plans describe the **ordered steps the system will take** (tool calls, orchestrator steps, planner reasoning sequences). They are system process structures expressed in runtime terms.

## What a commitment is, and why it is not a plan

A commitment is a **human responsibility structure** such as an open loop, project, next action, waiting state, or review obligation.

The authoritative contract for commitments is documented in:
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (core human commitment semantics)
- `docs/HUMAN-FLOWS.md` (lived human experience of commitments)

### The distinction

**Commitments describe what the human owes, is waiting on, or considers next.**
They are expressed in human-facing terms: "I owe", "I'm waiting on", "this is what's next for me", "I need to return to this".

**Execution plans describe what the system orders its own work to accomplish.**
They are expressed in system terms: tool calls, sequenced orchestrator steps, planner-generated reasoning.

They are related but fundamentally different:
- Commitments are about human responsibility and attention.
- Plans are about system process.
- A commitment may cause the system to generate a plan to help advance it.
- But generating a plan does not create a commitment.
- And completing a plan does not automatically close a commitment.

### Direction of causality

Execution plans **may support** human commitments. The system can generate a plan to help the human move a project forward, gather information for a decision, or make progress on a waiting state.

But this relationship is one-way:
- A human commitment may cause a plan to be generated.
- A completed plan may contribute evidence toward closing a commitment.
- But **a finished execution plan never automatically transitions a commitment to `done`.**

Commitment transitions belong to the human's decision (possibly assisted by the system), not to runtime plan completion.

**The human's commitment landscape is authoritative. The system's execution plans are subordinate to it.**

## Forbidden vocabulary collisions

The following terms are used distinctly in each layer and must NOT be reused across them:

| Term | Execution Only | Commitment Only | Why |
|------|---|---|---|
| `Plan` | Generated system artifact; sequence of tool calls or orchestrator steps | FORBIDDEN | A commitment is never called a "Plan"; it is not reducible to system sequencing |
| `Step` | Orchestrator action; element of an execution sequence | FORBIDDEN | A human next action is not a system step; system sequencing and human action are different concepts |
| `waiting` | Orchestrator awaiting a tool result; async operation paused | FORBIDDEN | Commitment-layer waiting (e.g., "I'm waiting for Alice's reply") is a human responsibility state, not system inactivity |
| `done` | Execution step finished; planner step completed; tool call returned | FORBIDDEN | A commitment is closed by human decision, not by system process completion |
| `next` | Next orchestrator step; next planner action in a sequence | FORBIDDEN | A human next action is a human responsibility; next system step is execution sequencing |
| `project` | Planner project; execution-layer grouping for orchestrator steps | FORBIDDEN | A human project is a multi-step commitment with a meaningful outcome; planner project is internal sequencing |

**Violation example:** If a finished planner project causes a human project commitment to auto-close, the vocabulary collision has caused a failure mode. The planner's "project" is not the human's commitment.

**Non-violation example:** System documentation may correctly state "the system generated a plan to help the user advance the hiring project commitment" (plan and project refer to different layers and serve different purposes).

## Acceptance Criteria

- [ ] This file contains a "## What an execution plan is" section that points to existing execution-artifact vocabulary without redefining it.
- [ ] This file contains a "## What a commitment is, and why it is not a plan" section that names the direction of causality: commitments are human responsibility structures; plans are system process structures; plans may support commitments but do not replace them.
- [ ] This file contains a "## Forbidden vocabulary collisions" section listing at least the terms `Plan`, `Step`, `waiting`, `done`, `next`, and `project` as non-shareable across the two layers.
- [ ] This file states explicitly that completion of an execution plan does not automatically close a commitment.
- [ ] This file does not propose a schema, event name, or new runtime component.
- [ ] This file does not modify `COMMITMENT_LAYER_CONTRACT.md` or any execution/orchestrator docs.

## How to Verify (Pre-Merge)

- Read this file side-by-side with `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` §"Relation to execution artifacts". Confirm the two docs agree.
- Read this file side-by-side with `docs/plans/V60_ARCHITECTURE_TARGET.md` §Delta 5. Confirm it is compatible with "commitment-first modeling that does not collapse projects, open loops, waiting states, and next actions into generic note lifecycle labels or execution-plan vocabulary".
- Apply the vocabulary-collision list to a sample orchestrator/planner doc reference and confirm no collisions are introduced.
- Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` are touched.

## Out of Scope

- Defining commitment states or transitions (see `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`).
- Defining the commitment vs note-state boundary (see `DEFINE_COMMITMENT_VS_NOTE_STATE.md`).
- Defining receipts (see `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`).
- Redesigning the planner or orchestrator.
- Modifying any runtime execution code.
- Creating a new "commitment orchestrator" or any such component.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/NAME_THE_COMMITMENT_FAMILY.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (§Relation to execution artifacts)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (§Delta 5)
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (§Execution Artifact — read-only reference)

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_VS_EXECUTION_PLAN". Use the acceptance criteria above as the issue contract.
