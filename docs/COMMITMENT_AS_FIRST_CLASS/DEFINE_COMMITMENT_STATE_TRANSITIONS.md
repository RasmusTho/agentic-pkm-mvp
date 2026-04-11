---
name: Define Commitment State Transitions
description: Name the commitment state family and require that transitions be explainable and distinct from maturity and review posture
task_id: COMMITMENT-FIRST-CLASS-04
source_anchor: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Primary concepts
parent_capability: Commitments as a first-class semantic family
prerequisites: [COMMITMENT-FIRST-CLASS-01]
depends_on: [NAME_THE_COMMITMENT_FAMILY.md]
can_parallelize_with: [DEFINE_COMMITMENT_VS_NOTE_STATE, DEFINE_COMMITMENT_VS_EXECUTION_PLAN, DEFINE_COMMITMENT_RECEIPT_REQUIREMENT]
---

State: Specification for the commitment state family and the explainability requirement. Docs-only.

# Define Commitment State Transitions

## Purpose

This task names the commitment states the v6.0 architecture must carry, and requires every transition between them to be explainable to the user. It exists so the user can offload a commitment with confidence that, later, when the system says "this is done" or "this is waiting", the user can ask "why?" and get a legible answer. Without explainable transitions, the user cannot trust the system's reporting of their commitment landscape, and the cognitive prosthetic fails.

## What This Task Does

Write the following contract sections in this file:

1. "## The commitment state family" — name the states a commitment can occupy:
   - `open` (the commitment exists and is active but has no clarified next action yet)
   - `next` (the commitment has a clarified next action that can be taken now)
   - `waiting` (progress depends on another actor, another event, or a future condition)
   - `blocked` (progress is stalled by something the user or system has not yet resolved; distinct from `waiting` in that `blocked` implies unresolved impediment rather than expected external dependency)
   - `done` (the commitment is intentionally closed — either completed, abandoned with intent, or rolled into another commitment)

   Explicitly state that `done` covers both "finished" and "explicitly dropped"; a commitment can become `done` by the user deciding it no longer matters.

2. "## What these states are NOT" — explicitly rule out:
   - These are NOT `review_state` values. A commitment in `open` is NOT the same as a note in `draft`.
   - These are NOT `maturity` values. A commitment in `done` is NOT the same as a note with `maturity = evergreen`.
   - These are NOT execution-plan states. A commitment in `waiting` is NOT the same as an orchestrator step awaiting a tool result.
   - Unknown or partial state is a legal position. A commitment may exist without yet having a clarified state; the system must not fabricate certainty.

3. "## Transition explainability requirement" — the core trust rule:
   - Every commitment state transition must be explainable after the fact.
   - An explanation must name: which commitment, which states (before/after), when, and why (user action, review cycle, external trigger, system suggestion accepted by user).
   - The system must not auto-close a commitment based solely on runtime execution completion, retrieval signals, salience decay, or staleness heuristics. Such signals may SURFACE a commitment for review, but only a user-accepted action may close it.

4. "## Allowed transitions (non-exhaustive)" — a short, concept-level set of transitions. NOT a state-machine schema. For example:
   - `open -> next` when a next action is clarified.
   - `open -> waiting` when the user recognizes an external dependency.
   - `next -> waiting` when the next action's completion reveals a new dependency.
   - `waiting -> next` when the awaited condition is satisfied.
   - `next -> done` when the user marks the commitment complete.
   - `open -> blocked` when impediment is named; `blocked -> open` when impediment is cleared.
   - `any -> done` by explicit user decision (including intentional drop).

   State that this list is illustrative; the point is that transitions are finite, nameable, and explainable, not that this exact graph is the schema.

## Concretely

When complete, a reader can take a sample commitment and describe its state over time in user-facing terms: "this project was open for a week, then the user clarified a next action so it became next, then it went to waiting because the user was waiting on a reply from Bob, then to next again on Monday when Bob replied, and finally to done on Wednesday when the user confirmed completion." Each step in that narrative must be explainable with the four fields above (commitment, before, after, why).

The contract must also include a non-fabrication rule: if the system does not know the current state of a commitment, the correct answer is `unknown`, not a guess. `unknown` is a legal state during clarification.

## Why This Matters

The user will only trust the system to carry their commitments if they can later ask "what happened to that?" and get a legible answer. An unexplained transition is worse than no tracking at all, because it introduces the suspicion that the system is quietly rewriting the user's responsibility landscape. The cognitive-prosthetic value of the system depends on the user being able to audit any commitment transition in user-recognizable terms.

Concretely, missing explainability causes these failure modes:

- The user sees a commitment marked `done` and cannot remember doing that; trust collapses instantly.
- The system auto-closes stale commitments based on recency heuristics; real responsibilities silently disappear.
- The system treats waiting as inactivity and drops the commitment from visible working set; the user no longer feels supported.

The explainability requirement in this file is the architectural defense against all three.

## Acceptance Criteria

- [ ] This file contains a "## The commitment state family" section naming `open`, `next`, `waiting`, `blocked`, `done`, plus an explicit note that `unknown` / partial state is legal.
- [ ] This file contains a "## What these states are NOT" section explicitly distinguishing commitment states from `review_state`, `maturity`, and execution-plan states.
- [ ] This file contains a "## Transition explainability requirement" section requiring each transition to be explainable with at least: commitment identity, before-state, after-state, time, and cause.
- [ ] This file contains a "## Allowed transitions (non-exhaustive)" section with illustrative transitions, clearly marked as illustrative rather than schema.
- [ ] This file explicitly forbids auto-closure of commitments based on runtime execution completion, salience decay, or staleness alone.
- [ ] This file does not propose a DB schema, event payload, or concrete state machine implementation.
- [ ] This file does not contradict `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`.

## How to Verify (Pre-Merge)

- Read this file side-by-side with `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`. Confirm the state family is compatible with the concepts `Commitment`, `Project`, `Next Action`, `Waiting`, `Review Cycle`.
- Read this file side-by-side with `docs/CONCEPTS/STATE_AXES_CONTRACT.md`. Confirm no commitment state name is confused with a canonical `review_state` or `maturity` value.
- Apply the "unexplained transition" failure-mode list to a sample commitment history and confirm the contract prevents it.
- Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` are touched.

## Out of Scope

- Designing the storage or event shape of commitment transitions.
- Designing the UI for commitment transitions.
- Implementing any auto-surfacing of stale commitments (resurfacing is explicitly downstream; see the v5.6 slice and V60 architecture target for boundaries).
- Defining the commitment-receipt contract in full (see `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`).
- Modifying `review_state` normalization or promotion.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/NAME_THE_COMMITMENT_FAMILY.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (§Delta 5, §Pillar 9 "Accountability and explainability")

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS". Use the acceptance criteria above as the issue contract.
