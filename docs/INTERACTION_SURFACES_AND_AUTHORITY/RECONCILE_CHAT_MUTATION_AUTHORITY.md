---
name: Reconcile Chat Mutation Authority
description: Surface the Chat read-only-vs-canvas contradiction as a bounded, named, owned design decision with explicit evaluation criteria and two candidate resolutions
task_id: INTERACTION-05
source_anchor: docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Fixed Decisions :: Deep Agents start in Chat before Panel
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01, INTERACTION-02, INTERACTION-03, INTERACTION-04, INTERACTION-06]
depends_on:
  - NAME_THE_THREE_INTERACTION_SURFACES.md
  - DEFINE_PANEL_AUTHORITY_BOUNDARY.md
  - DEFINE_CHAT_AUTHORITY_BOUNDARY.md
  - DEFINE_AUTOMATION_SURFACE_AUTHORITY.md
  - STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md
can_parallelize_with: []
---

State: Keystone decision task. Its whole job is to surface the Chat mutation contradiction. The reconcile outcome is not inside this spec; this spec creates the frame the decision will land in.

# Reconcile Chat Mutation Authority

## Purpose

Name the live contradiction about Chat's mutation boundary, lay out the evaluation criteria, describe two candidate resolutions, identify a decision owner slot, and set an acceptance condition for what "decided" means. This task does not answer the question. Its success criterion is that the question becomes small and owned, not that it becomes closed.

## The contradiction, stated exactly

Three docs speak about Chat's mutation boundary, and they do not agree:

1. **V60 working plan §Fixed Decisions.** `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` says: Chat is the safer Deep Agent entry surface because it is read-only.
2. **V60 working plan §Interaction Model.** The same document later says Chat starts read-only but may later participate in governed mutation paths, with the decision deferred.
3. **Design principles.** `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority already permits multiple governed mutation paths and explicitly says the design goal is governed mutation, not a single exclusive mutation surface.
4. **Product intent.** The user's stable design intent, carried across sessions, treats Chat as a canvas-like thinking surface where externalized thought can be manipulated and optionally committed through a governed path. Canvas is a posture, not a runtime choice; it is compatible with governed mutation and incompatible with permanent read-only identity.

The contradiction is not a bug in any single doc. It is the result of the working plan freezing a cautious early decision before the higher-authority design contract was fully written down. The reconcile task's job is to make this explicit so the project can decide in the open instead of letting one framing silently win.

## Evaluation criteria

Any resolution to the Chat mutation question must be judged against these criteria, in order:

1. **Governance before autonomy.** Does the resolution preserve `docs/DESIGN_PRINCIPLES.md` §Governance Before Autonomy? Read-only cognition should precede mutation-capable autonomy; the resolution must not introduce autonomous mutation ahead of governance readiness.
2. **Gated execution invariant.** Does the resolution preserve the invariant stated in `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`? No interaction surface mutates durable state without policy + validation + event pipeline, and LLM reasoning alone never triggers execution.
3. **Canvas is not ASK.** Does the resolution keep the canvas-vs-ASK distinction intact? A resolution that restores receive-query / return-answer semantics under the canvas label fails this criterion even if it otherwise looks safe.
4. **Receipt legibility.** Does the resolution describe, at least at the level of "receipts live here," where Chat's accountability surface is? The user must be able to audit what the canvas did on their behalf. Missing receipt locality is a fail.
5. **Parallel-safety for current runtime.** Does the resolution leave Panel runtime, event schemas, and the current mutation pipeline untouched until an explicit future capability is opened? A resolution that requires immediate runtime change fails this criterion.
6. **User-needs coverage.** Does the resolution serve "externalize and manipulate thought" and "trust what the system did" simultaneously? A resolution that chooses one at the cost of the other fails.
7. **Reversibility at the doc layer.** If the resolution proves wrong within one or two releases, can it be reversed by editing docs, not by unwinding shipped code?

## Candidate resolutions

Exactly two candidate resolutions are named here. The task does not pick between them. Reviewers and the decision owner may add a third candidate during review; naming a third candidate does not resolve the decision.

### Candidate A — DESIGN_PRINCIPLES wins

- DESIGN_PRINCIPLES is the higher-authority contract. The V60 working plan's "Chat is read-only" becomes narrowed to apply specifically to the Deep Agent introduction phase, not to Chat's identity.
- Chat is a canvas-shaped interaction surface. It may carry governed mutation rights, which are distinct from Panel's command-oriented mutation rights but use the same gated-execution pipeline.
- The working plan text in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` is recommended (not required by this task) to be edited in a follow-up owner-doc promotion PR so the two docs agree.
- The Deep Agent rollout still begins in a read-only slice of Chat, because read-only cognition precedes mutation-capable autonomy. "Chat starts read-only for Deep Agents" is preserved without making Chat's identity read-only.
- Receipt locality for canvas-commit actions is named in a follow-up task, not here.

Arguments for: aligns docs with the higher-authority contract; preserves product intent; preserves user-needs coverage; reversible at docs layer.

Arguments against: widens the Chat definition before any implementation exists; creates a temporary doc inconsistency until the follow-up promotion PR lands; puts more weight on the reconcile task to prevent scope drift.

### Candidate B — V60 plan wins

- The V60 working plan's "Chat is read-only" becomes the stable definition. Chat is structurally read-only, and the multiple-governed-mutation-paths clause in DESIGN_PRINCIPLES is reinterpreted to cover Panel plus Automation (plus any later surface) without including Chat.
- Canvas-like thinking is explicitly rejected as a mutation-carrying posture. Chat can still be used as a thinking surface in the sense of receiving and displaying cognition, but it does not hold a commit-through-governance path.
- Product intent (canvas-Chat as mutation-carrying) is recorded as considered and rejected, with reasoning.
- DESIGN_PRINCIPLES is either left as-is (with the multiple-paths clause interpreted narrowly) or a follow-up promotion PR narrows its language.

Arguments for: preserves the strictest reading of Governance Before Autonomy; keeps the current working plan stable; lowest short-term risk.

Arguments against: contradicts product intent; narrows DESIGN_PRINCIPLES retrospectively; reintroduces the risk of ASK-style Q&A by leaving no canvas posture at all; leaves the "externalize and manipulate thought" user need without a home.

## Decision owner and process

Decision owner slot: the v6.0 architecture owner (name to be filled in during review). The decision owner is the person whose sign-off closes this task.

Process:

1. Reviewers of this spec confirm the contradiction is stated accurately and the two candidate resolutions are stated fairly.
2. Reviewers may add a third candidate resolution before the decision owner takes the decision. A third candidate must pass all evaluation criteria above to be considered.
3. The decision owner selects a resolution, records the selection as a decision entry in this file's "Decision" section (see acceptance below), and triggers a follow-up owner-doc promotion PR if the selection requires edits to docs outside this directory.
4. Until the decision owner acts, every other task in this capability treats the Chat mutation boundary as open and defers to this file.

## Acceptance condition

The task is accepted when either (a) or (b) is true, and neither (a) nor (b) forces a change outside this directory without a follow-up owner-doc promotion PR.

(a) **Decision recorded.** A Decision section is added to this file that names the chosen resolution (A, B, or a named third candidate), the decision owner, the date, the reasoning, and the list of follow-up edits (if any) required in other docs. The follow-up edits are not performed in this capability; they are queued as a separate owner-doc promotion capability.

(b) **Decision held open.** A Decision section is added to this file that states the decision is held open, names the decision owner, names the blocking condition (for example, "pending first Deep Agent proof-of-concept in read-only Chat"), and sets an explicit re-evaluation trigger. The rest of the capability can ship with the Chat mutation boundary marked as open as long as (b) is in place with an owner and a trigger.

Neither outcome is allowed to quietly let one framing win by default. If no Decision section is added, the task is not accepted.

## What this task must not do

- Pick a resolution inside the body of the spec.
- Edit any file outside `docs/INTERACTION_SURFACES_AND_AUTHORITY/`.
- Recommend a runtime implementation.
- Recommend a Chat front-end location (inside or outside Obsidian).
- Introduce Deep Agents.
- Change the gated-execution invariant.
- Add candidate resolutions that violate any evaluation criterion without flagging the violation.

## Concretely

The deliverable is this file with a `## Decision` section added during acceptance, in the shape specified in the acceptance condition. Until the decision owner acts, the `## Decision` section is placeholder text:

```
## Decision

Status: OPEN.
Owner: <to be assigned during review>.
Blocking condition: <to be named>.
Re-evaluation trigger: <to be named>.
```

## Why This Matters

The Chat mutation question is the highest-leverage open decision in the v6.0 interaction model. Letting it be answered by accident — by one doc surface quietly outweighing another — would either block the canvas-Chat product intent forever or widen mutation authority without deliberate governance. Naming the decision is how the project avoids both failure modes.

## Acceptance Criteria

- [ ] The contradiction is stated explicitly, citing at least `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model, and `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority.
- [ ] Seven evaluation criteria are listed and each is testable against a candidate resolution.
- [ ] Exactly two candidate resolutions are named: "DESIGN_PRINCIPLES wins" and "V60 plan wins". A third may be added in review but must pass the criteria.
- [ ] Each candidate has explicit arguments-for and arguments-against.
- [ ] A decision owner slot exists and is marked as to-be-assigned.
- [ ] An acceptance condition is stated that allows either a recorded decision or an owned open deferral, but not silent drift.
- [ ] The task does not recommend any edit to files outside this directory inline; it recommends follow-up owner-doc promotion PRs instead.
- [ ] No part of this file presumes which resolution wins.

## How to Verify (Pre-Merge)

Docs review:

- A reviewer can read this file and state the contradiction in their own words.
- A reviewer can state both candidate resolutions and explain at least one argument for and against each.
- A reviewer can point to the exact acceptance condition for closing the decision.
- A reviewer cannot find any sentence in this file that presumes either resolution.
- A reviewer can find the placeholder `## Decision` section.

## Out of Scope

- Picking a resolution.
- Editing DESIGN_PRINCIPLES, V60 plan, ROADMAP, PANEL_AGENT, or DOCS_INDEX.
- Introducing a Chat implementation.
- Introducing a Deep Agent.
- Deciding where Chat lives (Obsidian, standalone, other).
- Changing any event or schema.

## Related Docs

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10A
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority
- `docs/DESIGN_PRINCIPLES.md` §Governance Before Autonomy
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- Sibling: `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`
- Sibling: `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`
- Sibling: `NAME_THE_THREE_INTERACTION_SURFACES.md`

## Related GitHub Issues

None. If the decision owner selects a resolution that requires edits to docs outside this directory, the follow-up owner-doc promotion PR may be tracked as a separate issue, but it is out of scope for this capability.

---

**Status:** Decision recorded. Candidate A selected. Follow-up owner-doc promotion queued.

## Decision

Status: RESOLVED — Candidate A (DESIGN_PRINCIPLES wins).
Owner: Rasmus Thornberg (v6.0 architecture owner).
Date: 2026-04-11.

### Selected resolution

**Candidate A — DESIGN_PRINCIPLES wins.** Chat is a canvas-shaped interaction surface and may carry governed mutation rights through the same gated-execution pipeline used by Panel and Automation. "Chat is read-only" from the V60 working plan is narrowed to apply specifically to the Deep Agent introduction phase, not to Chat's identity. The Deep Agent rollout still begins in a read-only slice of Chat to satisfy Governance Before Autonomy; that constraint applies to *Deep Agents in Chat*, not to *Chat itself*.

### Reasoning

1. **Higher-authority contract.** `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority is the authoritative design contract for mutation surfaces. The V60 working plan §Fixed Decisions is a forward-line working plan that froze a cautious early framing before that contract was fully written down. When the two disagree, the design contract wins by construction.
2. **Product intent is stable across sessions.** The user's design intent treats Chat as a canvas where externalized thought can be manipulated and optionally committed through governance. That intent is not a session preference; it is the cognitive-prosthetic posture v6.0 is built around. A resolution that permanently forecloses Chat mutation forecloses that posture.
3. **Canvas ≠ ASK.** Canvas posture is the explicit alternative to ASK Q&A semantics. Foreclosing Chat mutation would leave the system with no canvas-capable surface and would push the user back into ASK-shaped interaction by default — the exact failure FINDING_AND_REORIENTING/DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER is built to prevent.
4. **Governance Before Autonomy is preserved.** Candidate A does not introduce autonomous mutation. Chat mutation, when it ships, runs through the same policy + validation + event pipeline as Panel mutation. The Deep Agent rollout still begins read-only.
5. **Gated execution invariant is preserved.** Per `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`, no surface mutates durable state without policy + validation + event pipeline; LLM reasoning alone never triggers execution. Candidate A explicitly inherits this invariant for Chat-originated mutations.
6. **Reversibility is preserved.** No runtime exists for canvas-Chat mutation today. The decision is reversible at the docs layer until the first Chat mutation slice is opened as its own capability.
7. **Multi-user neutrality.** Per the multi-user-stance memory, this decision must not block a future multi-user evolution. Candidate A treats the canvas-commit pipeline as gated execution, which is multi-user-neutral; Candidate B's "Chat is structurally read-only" framing would be harder to relax later.

### Evaluation criteria scorecard

| Criterion | Candidate A (selected) | Candidate B |
| --- | --- | --- |
| Governance before autonomy | Pass — Deep Agents still start read-only in Chat | Pass |
| Gated execution invariant | Pass — Chat mutations inherit the gated pipeline | Pass |
| Canvas is not ASK | **Pass** — canvas posture preserved | **Fail** — no canvas surface left |
| Receipt legibility | Deferred to follow-up canvas-commit capability; not blocking | N/A |
| Parallel-safety for current runtime | Pass — no runtime change required by this decision | Pass |
| User-needs coverage ("externalize and manipulate" + "trust what the system did") | **Pass** — both served | **Fail** — externalize-and-manipulate has no home |
| Reversibility at docs layer | Pass — no shipped code depends on this | Pass |

Candidate B fails criteria 3 and 6. Candidate A passes all seven.

### Follow-up owner-doc promotion edits required

These edits are **not** performed by this capability. They are queued as a separate owner-doc promotion lane and must land before any Chat-mutation runtime work begins.

1. **`docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions.** Narrow "Chat is read-only" to "Deep Agents start in a read-only Chat slice." Cite this decision.
2. **`docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model.** Replace "Chat starts read-only but may later participate in governed mutation paths" with the canvas-shaped framing from `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`. Cite this decision.
3. **`docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority.** No edit required. The existing "multiple governed mutation paths" clause is the contract this decision invokes.
4. **`docs/ROADMAP.md`.** Add a v6.x slot for "canvas-commit pipeline (Chat-originated gated mutation)" as a future capability lane. No date.
5. **`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md`.** Already framed as canvas-capable; remove any "boundary is open" hedges that this decision now closes.

### Out of scope for this decision

- The Chat front-end implementation location (inside Obsidian, standalone, web, etc.) remains a separate decision per the user's stable position that "Chat may live outside Obsidian."
- The first Chat-mutation runtime slice. That requires a separate `feature-breakdown` pass once the owner-doc promotion edits are merged.
- Receipt locality and shape for canvas-commit actions. Deferred to the canvas-commit capability lane.
- Any change to Panel, Automation, or Deep Agent behavior beyond the narrowing of "Chat is read-only" to apply only to the Deep Agent introduction phase.

### Re-evaluation trigger

This decision is reversible at the docs layer until the first Chat-mutation runtime slice is implemented. After that point, reversing requires unwinding shipped code and is not a docs-layer move. If the canvas-commit pipeline cannot be designed to satisfy `STATE_EXECUTION_AUTHORITY_REMAINS_GATED` and `DESIGN_PRINCIPLES` §Governance Before Autonomy simultaneously, the decision must be re-opened before the first runtime slice.
