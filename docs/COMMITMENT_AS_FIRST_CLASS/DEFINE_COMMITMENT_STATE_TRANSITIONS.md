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

## The commitment state family

A commitment can occupy one of five primary states, plus an `unknown` state for commitments still undergoing clarification.

**Primary states:**

- `open`: the commitment exists and is active but has no clarified next action yet. The user is aware of the responsibility and it matters, but the required next step is not yet clear. A commitment may remain `open` while the user gathers context, refines scope, or waits for more information before determining what should be done.

- `next`: the commitment has a clarified next action that can be taken now. The system and the user both know what should happen next, and that next step is available to begin.

- `waiting`: progress depends on another actor, another event, or a future condition that is not currently under direct control. This is distinct from `open` in that the user expects something external to change before the next actionable step can be taken.

- `blocked`: progress is stalled by something the user or system has not yet resolved. This is distinct from `waiting` in a specific way: `blocked` implies an unresolved impediment (something that must be actively removed or clarified), whereas `waiting` implies an expected external dependency (something the user is watching for). A commitment may move from `blocked` to `open` or to `next` once the impediment is addressed.

- `done`: the commitment is intentionally closed. This covers both "finished" (completed successfully) and "explicitly dropped" (the user decided it no longer matters, was rolled into another commitment, or no longer holds the user's attention). A commitment can become `done` by user decision at any time; the user controls closure, not heuristics.

**Unknown or partial state:**

A commitment may exist without yet having a clarified state. `unknown` is a legal position during clarification. The system must not fabricate certainty by assigning a state the user has not endorsed. If the user has not clarified whether a commitment is `open`, `waiting`, or something else, the correct answer is `unknown`, not a guess.

## What these states are NOT

**Commitment states are NOT `review_state` values.**

A commitment in `open` is NOT the same as a note in `draft` (`review_state`). A note can be in `draft` review_state (still open for mutation) while its corresponding commitment is in `next` (ready to act on). Conversely, a note can be in `protected` review_state (guarded against change) while its commitment is `waiting` (expecting an external event).

**Commitment states are NOT `maturity` values.**

A commitment in `done` is NOT the same as a note with `maturity = evergreen`. A note may reach `evergreen` maturity (becoming a durable reference) while the commitment it represents is `done` (closed and off the active responsibility list). A note may be `raw` or `developing` in maturity while the commitment it supports is in `next` and actively being worked.

**Commitment states are NOT execution-plan states.**

A commitment in `waiting` is NOT the same as an orchestrator step awaiting a tool result. An execution plan may have steps in a "pending" or "waiting for input" state while the commitment those steps support is in `next` (the user is actively choosing which next action to take). Conversely, a commitment may be in `waiting` (awaiting an external event) while no active execution plan is running.

Execution plans are generated, transient process structures. Commitment states are part of the human's persistent responsibility model.

## Transition explainability requirement

The core trust rule: **every commitment state transition must be explainable after the fact.**

When a commitment moves from one state to another, the user must be able to ask "what happened to that commitment?" and receive a legible answer. An unexplained transition damages the trust on which the cognitive prosthetic depends.

**What an explanation must include:**

1. **Commitment identity** — which commitment transitioned (by name, ID, or unique reference)
2. **Before-state and after-state** — the exact states involved in the transition
3. **Timestamp** — when the transition occurred
4. **Cause** — why the transition happened: 
   - a user action (marked complete, clarified a next action, named an impediment)
   - a review cycle (the user re-examined and updated it)
   - an external trigger (the awaited event occurred)
   - a system suggestion accepted by the user (the system proposed a state change and the user endorsed it)

**Non-fabrication rule:**

The system must not auto-change a commitment state based solely on:
- runtime execution completion,
- retrieval signals or query results,
- salience decay or staleness heuristics,
- or loss of recent activity.

**However**, automatic state transitions ARE permissible when:
- an external trigger is observable and deterministic (e.g., the awaited event actually occurred, a scheduled time arrived, a named async dependency resolved),
- the transition is explainable with the four required fields (commitment, before-state, after-state, cause),
- and the user retains visibility and agency (can review what changed and why).

The distinction is clear: transitions driven by **observable external facts** (`waiting -> next` because the reply arrived) are trustworthy. Transitions driven by **confidence heuristics** about staleness are not. The user decides when heuristics justify surfacing a commitment for review, but observable triggers justify automatic state changes.

## Allowed transitions (non-exhaustive)

The following transitions are illustrative, not exhaustive. The point is that transitions are finite, nameable, and explainable — not that this exact graph is a complete state machine.

**Common transitions:**

- `open -> next` when a next action is clarified (user decides what should be done next)
- `open -> waiting` when the user recognizes an external dependency (user discovers something else must happen first)
- `next -> waiting` when the next action's completion reveals a new dependency (user starts the next action and discovers an external blocker)
- `waiting -> next` when the awaited condition is satisfied (the awaited event occurs, and the next action becomes available)
- `next -> done` when the user marks the commitment complete (user confirms the work is finished or decides to close it)
- `open -> blocked` when an impediment is named (user identifies what is in the way)
- `blocked -> open` when the impediment is cleared (the blocking issue is resolved, and the commitment is open again for clarification)
- `any -> done` by explicit user decision (at any point, the user may close a commitment, deciding it no longer matters, has been abandoned, or has been merged into another commitment)

This list is illustrative. New transitions are permissible as long as they remain explainable.

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
