---
name: Parent Feature Issue — Commitments as a distinct semantic family
description: Parent feature issue contract for the v6.0 commitment-first-class capability
task_id: COMMITMENT-FIRST-CLASS-FEATURE
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 5 / Delta 5
parent_capability: Commitments as a first-class semantic family
prerequisites: none
depends_on: []
can_parallelize_with: []
---

State: Parent feature issue contract for the v6.0 "commitments as a distinct semantic family" capability. Docs-only scope.

# [Feature] Commitments as a distinct semantic family

## Context

The v6.0 architecture target explicitly lists commitments as a distinct semantic family that must be preserved separately from artifact lifecycle, generic note state, and execution-plan vocabulary (`docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 5, §Delta 5). Today, the runtime and the docs still make it too easy to read commitment structures as if they were `review_state` transitions, maturity labels, or planner/orchestrator execution plans. That flattening damages the user's trust that the system is recognizably helping with GTD-like cognitive offloading.

There is already an active v5.6 commitment runtime slice (`docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`) that describes the first bounded runtime-enablement move for commitment support. That slice is deliberately narrow and is not a v6 realization. This feature spec sits upstream of it semantically: this spec describes what commitments ARE and what the architecture must keep distinct from them, while the v5.6 slice describes the first place runtime may begin to carry commitment-oriented structures without collapsing them.

This feature exists because the semantic family must be named and bounded at the docs layer before any further runtime work can safely land.

## Scope

Produce a bounded specification directory at `docs/COMMITMENT_AS_FIRST_CLASS/` that:

- Names Commitment, Project, Next Action, Waiting, and Review Cycle as a distinct semantic family.
- Draws the explicit boundary between a commitment and a note carrying `review_state` or maturity.
- Draws the explicit boundary between a commitment and an execution plan.
- Names the commitment state family (open, next, waiting, blocked, done) and requires that transitions be explainable.
- Requires that commitment state transitions leave a receipt the user can trust, cross-referenced to (not prescribing) the persistence-surface receipt lane.
- Reconciles this spec with the v5.6 commitment runtime slice, flagging any terminology drift rather than silently resolving it.

Scope is docs-only. No code, no schema, no runtime change.

## Source Anchors

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 5 "Commitments remain a distinct semantic family"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Delta 5 "From flattened commitment handling to commitment-first semantics"
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (read-only reference — first runtime enablement move)
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (concept SoT — not rewritten by this spec)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (boundary reference — `review_state` and `maturity`)
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/HUMAN-FLOWS.md`

## Constraints

- Docs-only. No edits outside `docs/COMMITMENT_AS_FIRST_CLASS/`.
- Do not touch `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`. Read it, reconcile against it, do not edit it.
- Do not rewrite `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`. This spec sits beside it and clarifies architectural placement; it does not replace it.
- Do not modify `docs/DOCS_INDEX.md`.
- Do not design DB schema, event payloads, or table layouts (`V60_ARCHITECTURE_TARGET.md` §Non-goals).
- Do not implement the v5.6 commitment runtime slice.
- Do not modify `review_state` / `maturity` handling anywhere in the repo.
- Do not touch the promotion path.
- Do not create GitHub issues from inside this spec delivery. Issue creation is a downstream `feature-breakdown` step.
- The cognitive-prosthetic framing (user externalizes open loops; user trusts the system's commitment handling) must be preserved explicitly in every task file — not optional decoration.

## Acceptance Criteria

- [ ] `docs/COMMITMENT_AS_FIRST_CLASS/README.md` exists and states the human need served (cognitive-prosthetic framing), the boundary of what this capability is NOT, the v5.6 slice dependency, and the reading order for task files.
- [ ] `docs/COMMITMENT_AS_FIRST_CLASS/PARENT_FEATURE_ISSUE.md` (this file) exists and satisfies the parent feature issue contract from the feature-breakdown skill.
- [ ] `NAME_THE_COMMITMENT_FAMILY.md` names Commitment, Project, Next Action, Waiting, Review Cycle as distinct semantic kinds and states what they are separate from.
- [ ] `DEFINE_COMMITMENT_VS_NOTE_STATE.md` gives an explicit contract separating commitments from notes carrying `review_state` / `maturity`, and names the trust damage of flattening.
- [ ] `DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md` gives an explicit contract separating commitments from execution plans and forbids vocabulary reuse.
- [ ] `DEFINE_COMMITMENT_STATE_TRANSITIONS.md` names the commitment state family and requires explainable transitions distinct from maturity/review.
- [ ] `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md` requires commitment-state transitions to leave a receipt and cross-references the persistence-surface receipt lane without prescribing it.
- [ ] `RECONCILE_WITH_V56_COMMITMENT_SLICE.md` reads the v5.6 slice, states the v6 spec's position relative to it, and flags any terminology drift explicitly.
- [ ] No file outside `docs/COMMITMENT_AS_FIRST_CLASS/` is modified as part of delivering this feature.
- [ ] The capability can be referenced by name from `docs/plans/V60_ARCHITECTURE_TARGET.md` Pillar 5 in future docs passes.

## Out of Scope

- Implementing any runtime support for commitments (including the v5.6 slice).
- Modifying `review_state` or `maturity` reads, writes, normalization, or tests.
- Modifying promotion, ingest, watcher, or mirror logic.
- Designing or proposing concrete commitment schema, event names, database tables, or API payloads.
- Creating data migrations or backfill scripts.
- Rewriting `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` or any other core concept SoT doc.
- Editing `docs/DOCS_INDEX.md`, `docs/STATUS.md`, `docs/ARCHITECTURE.md`, or `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`.
- Creating GitHub issues.

## Suggested Validation

- A reader unfamiliar with the v6.0 work can open `docs/COMMITMENT_AS_FIRST_CLASS/` and, using only the task files there, answer:
  - What is a commitment?
  - How is a commitment different from a note with `review_state = draft`?
  - How is a commitment different from a planner execution plan?
  - What states can a commitment be in, and why must transitions be explainable?
  - What does this spec say about the v5.6 commitment runtime slice?
- Cross-read sanity check: no task file in this directory contradicts `COMMITMENT_LAYER_CONTRACT.md` or `V60_ARCHITECTURE_TARGET.md` Pillar 5 / Delta 5.
- Drift surface: `RECONCILE_WITH_V56_COMMITMENT_SLICE.md` names any term where the v5.6 runtime slice and this v6 spec diverge, rather than silently unifying them.

## Source Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ARCHITECTURE.md`

## Implementation Tasks

Each task file below lives in this directory and is self-contained. Intended order:

1. `NAME_THE_COMMITMENT_FAMILY.md` — name the semantic family and what it is separate from.
2. `DEFINE_COMMITMENT_VS_NOTE_STATE.md` — commitment vs `review_state`/`maturity` boundary.
3. `DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md` — commitment vs execution plan boundary.
4. `DEFINE_COMMITMENT_STATE_TRANSITIONS.md` — commitment states and explainable transitions.
5. `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md` — receipts for commitment transitions.
6. `RECONCILE_WITH_V56_COMMITMENT_SLICE.md` — alignment with the v5.6 runtime slice, drift flagged not resolved.

Tasks 1–5 may be authored in parallel, but task 1 should anchor the vocabulary first. Task 6 must be last because it consumes 1–5 plus the v5.6 slice.

## Verification Path

Each task file is verified by:

- It follows the feature-breakdown frontmatter and section shape.
- It preserves the cognitive-prosthetic framing in its Purpose / Why This Matters sections.
- It does not propose changes outside `docs/COMMITMENT_AS_FIRST_CLASS/`.
- It does not redefine `review_state`, `maturity`, or promotion semantics.
- It does not design schema, tables, or event payloads.
- It does not contradict `COMMITMENT_LAYER_CONTRACT.md` or `V60_ARCHITECTURE_TARGET.md` Pillar 5 / Delta 5.

The parent feature is verified when all six task files pass these checks and the README acceptance checklist is green.

## Validation / Acceptance Path

Post-merge validation surfaces:

- **Docs consistency check.** A future v6 architecture review pass can cite this directory for the commitment family definition without contradiction.
- **v5.6 slice alignment.** When the v5.6 commitment runtime slice is picked up for implementation, `RECONCILE_WITH_V56_COMMITMENT_SLICE.md` is the meeting point — any drift surfaced there is resolved in the implementation lane, not by quietly editing this spec.
- **Cognitive-prosthetic honesty check.** When the first user-facing commitment flow is validated, the user must be able to describe an open loop, mark it as a commitment, and see the system distinguish it from both a note and an execution plan, with commitment state transitions explainable. If that validation fails because the distinctions are not recognizable to the user, the failure lands against this spec, not against the runtime slice alone.
- **Owner-doc promotion trigger.** Owner docs (e.g. `docs/ARCHITECTURE.md`, `docs/STATUS.md`) are only updated to claim "commitments are a first-class semantic family" when the v5.6 runtime slice has landed AND the reconcile task confirms no outstanding terminology drift. This spec does not trigger owner-doc promotion on its own.
