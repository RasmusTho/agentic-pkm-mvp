---
name: Commitments as a First-Class Semantic Family Specification
description: System specification for treating commitments as a distinct semantic family in the v6.0 architecture target
type: specification
authority: SoT for the v6.0 commitment-as-first-class semantic capability; upstream of runtime realization
source_of_truth: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 5, Delta 5
related_docs:
  - docs/plans/V60_ARCHITECTURE_TARGET.md
  - docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md
  - docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md
  - docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md
  - docs/CONCEPTS/STATE_AXES_CONTRACT.md
  - docs/CONCEPTS/USER_NEEDS_MODEL.md
  - docs/HUMAN-FLOWS.md
---

State: Active specification for the v6.0 capability "Commitments as a distinct semantic family". Docs-only; no runtime changes are in scope.

# Commitments as a First-Class Semantic Family

This directory is the system-level specification for one v6.0 capability: treating human commitments as a distinct semantic family in the architecture, rather than letting them be flattened into `review_state`, artifact maturity, note metadata, or execution-plan vocabulary.

It is a specification, not a runtime plan. Each task file in this directory describes a piece of docs/contract work that must be done so the architecture can carry commitments as their own thing. None of the tasks modify runtime code.

## Human needs this serves

This is the classic cognitive-prosthetic capability for a second brain. The user must be able to externalize open loops, next actions, and waiting states to the system and trust that the system is recognizably helping with that burden. When the user says "I owe this", "I am waiting on this", or "this is what is next", the system must hold those as commitments and not as "a note with a review state" or "a planner execution step".

Concretely, two user needs drive this capability:

- **Carry commitments without mental overload.** The user should not have to re-remember every open loop every day. The system takes that weight by naming commitments, projects, next actions, waiting states, and review cycles as first-class structures.
- **Trust what the system did with a commitment.** Every commitment state transition must be inspectable after the fact, so the user can trust that the system is tracking responsibility honestly.

If the architecture flattens commitments into generic note state or execution-plan vocabulary, both of these needs collapse — the user loses the ability to externalize, and the user loses the ability to trust.

See `docs/CONCEPTS/USER_NEEDS_MODEL.md` and `docs/HUMAN-FLOWS.md` for the underlying human-need posture.

## What this capability is

The capability, stated in one sentence:

> Commitment, Project, Next Action, Waiting, and Review Cycle are named and preserved as a distinct semantic family in the v6.0 architecture, separate from artifact lifecycle, generic note state, and execution-plan language.

This spec defines what must be true in the docs and contract layer so later runtime work has a stable target to aim at.

## What this capability is NOT

This specification explicitly does not include:

- Implementing the v5.6 commitment runtime slice. That slice is the first runtime enablement move and has its own plan doc. This spec is upstream of it.
- Modifying `review_state` or `maturity` handling, in runtime or in tests.
- Modifying the promotion path, the promotion event, or any write-boundary logic.
- Designing a commitment DB schema, table layout, or event payload. `docs/plans/V60_ARCHITECTURE_TARGET.md` §Non-goals explicitly defers concrete schema.
- Creating data migrations or backfills.
- Rewriting `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`. That contract is the canonical concept SoT; this spec sits beside it and clarifies the v6.0 architectural placement, not the concept itself.
- Touching `docs/DOCS_INDEX.md`.
- Creating GitHub issues from these task files (issue creation is a separate downstream step).

Every task in this directory must be fully deliverable by editing files only inside `docs/COMMITMENT_AS_FIRST_CLASS/`.

## Dependency on the v5.6 commitment runtime slice

There is an active v5.6 commitment runtime slice. Its governing plan is `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`.

The relationship between the v5.6 slice and this v6.0 spec:

- The v5.6 slice is the **first runtime-enablement move** for commitment support. It is deliberately narrow.
- This v6.0 spec is the **semantic target** the v5.6 slice is a bridge toward. It describes what commitments ARE and what must remain separate from them in the architecture.
- This spec must not duplicate, replace, or contradict the v5.6 slice. It also must not pretend the slice has been fully realized.
- Terminology drift between the v5.6 slice and this v6 spec must be named, not silently resolved. The reconcile task in this directory is where that alignment work lives.

If this spec and the v5.6 slice disagree, the disagreement is flagged, not papered over.

## Reading order for task files

Read in this order on the first pass:

1. **[NAME_THE_COMMITMENT_FAMILY.md](NAME_THE_COMMITMENT_FAMILY.md)** — the core naming task. Names Commitment, Project, Next Action, Waiting, Review Cycle as distinct semantic kinds and states what they are distinct from.
2. **[DEFINE_COMMITMENT_VS_NOTE_STATE.md](DEFINE_COMMITMENT_VS_NOTE_STATE.md)** — the explicit boundary between a commitment and a note carrying a `review_state`/`maturity` label. Explains why flattening damages user trust.
3. **[DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md](DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md)** — the explicit boundary between a commitment (what the user owes or is waiting on) and an execution plan (how the system orders its own work).
4. **[DEFINE_COMMITMENT_STATE_TRANSITIONS.md](DEFINE_COMMITMENT_STATE_TRANSITIONS.md)** — the states a commitment can be in, how transitions must be explainable, and how those states stay distinct from maturity and review posture.
5. **[DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md](DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md)** — the requirement that commitment state transitions leave a receipt the user can trust. Cross-references the persistence-surface receipt lane without prescribing it.
6. **[RECONCILE_WITH_V56_COMMITMENT_SLICE.md](RECONCILE_WITH_V56_COMMITMENT_SLICE.md)** — the alignment task. Reads the v5.6 slice, states this spec's position relative to it, and flags any terminology drift or disagreement.

Tasks 1–5 can be worked on in parallel if needed, but task 6 must be done after tasks 1–5 because it depends on having something concrete to reconcile against. Task 1 is the strongest anchor and should generally be written first.

## Parent feature issue

See **[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)** for the bounded parent-feature issue contract (capability intent, acceptance criteria, verification path, validation path). That file is the source of truth for what it means for this capability to be "done" at the spec level.

## Acceptance

This capability is accepted when all of the following are true:

- [ ] All six task files in this directory are merged and cross-link cleanly.
- [ ] The v6.0 architecture docs can reference "commitments as a distinct semantic family" and point to this directory for the semantic contract.
- [ ] The v5.6 commitment runtime slice has been read and reconciled with this spec, with any terminology drift explicitly named in `RECONCILE_WITH_V56_COMMITMENT_SLICE.md`.
- [ ] Nothing in this spec rewrites `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`, modifies `review_state` handling, designs schema, or touches the v5.6 slice plan file.
- [ ] A reader coming in cold can answer: "what is a commitment vs a note vs an execution plan?" by reading only this directory.

## Relationship to GitHub issues

Each task file may later map to one or more GitHub issues under the `feature-breakdown` skill contract. Those issues are downstream of this directory. This directory does not create them.

## Navigation

- **v6.0 target architecture:** `docs/plans/V60_ARCHITECTURE_TARGET.md` (pillar 5, delta 5)
- **v6.0 capability evolution plan:** `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- **v5.6 runtime slice (upstream runtime plan — do not edit):** `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`
- **Core commitment concept contract (do not rewrite):** `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- **State axis contract (to stay distinct from):** `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- **User needs model:** `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- **Human flows:** `docs/HUMAN-FLOWS.md`

---

**Status:** Specification directory initialized. Ready for task-level authoring and downstream reconciliation with the v5.6 commitment runtime slice.
