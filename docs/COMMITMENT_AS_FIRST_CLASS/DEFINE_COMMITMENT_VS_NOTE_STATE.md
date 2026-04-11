---
name: Define Commitment vs Note State
description: Explicit contract separating commitments from notes carrying review_state or maturity; names the trust damage of flattening
task_id: COMMITMENT-FIRST-CLASS-02
source_anchor: docs/CONCEPTS/STATE_AXES_CONTRACT.md :: Core rule
parent_capability: Commitments as a first-class semantic family
prerequisites: [COMMITMENT-FIRST-CLASS-01]
depends_on: [NAME_THE_COMMITMENT_FAMILY.md]
can_parallelize_with: [DEFINE_COMMITMENT_VS_EXECUTION_PLAN, DEFINE_COMMITMENT_STATE_TRANSITIONS, DEFINE_COMMITMENT_RECEIPT_REQUIREMENT]
---

State: Specification for the commitment vs note-state boundary in the v6.0 commitment-first-class capability. Docs-only.

# Define Commitment vs Note State

## Purpose

This task draws the explicit boundary between a commitment (as named in `NAME_THE_COMMITMENT_FAMILY.md`) and a note carrying a `review_state` or `maturity` label. It exists because the single most tempting mistake — the one the v6.0 architecture target flags as Delta 5 — is to flatten commitments into "notes with some workflow metadata". When that happens, the user's trust in the system as a cognitive prosthetic collapses, because they can no longer recognize their own open loops in what the system is holding.

## What This Task Does

Write two contract sections in this file:

1. "## What a note with review_state is" — a short restatement, from the concept SoT, of what `review_state` and `maturity` mean (artifact review/mutation posture, artifact standing/durability). This is NOT a redefinition; it is a pointer so the boundary is unambiguous.
2. "## What a commitment is, and why it is not that" — an explicit contract that a commitment is about responsibility, attention, and progress over time, not about review or maturity posture of an artifact. Include a short table listing at least five collision points and resolving each to the correct side.
3. "## Why flattening damages user trust" — the cognitive-prosthetic framing, stated in user-recognizable terms.

The contract table must include at least these rows:

| Collision | Belongs on commitment layer | Belongs on state axes |
| --- | --- | --- |
| "I still owe this" | `Commitment` (open) | — (not a `review_state`) |
| "I'm waiting on X" | `Waiting` | — (not `draft`, not `archived`) |
| "This draft is still being edited" | — | `review_state = draft` / `maturity = draft` |
| "This note has been reviewed and should be stable" | — | `review_state = reviewed` / `maturity = stable` |
| "I need to come back to this next week" | `Review Cycle` / `Waiting` | — (not `review_state`) |
| "This note is now retired from editing" | — | `review_state = archived` |
| "This project is done" | `Commitment` (done) | — (not `maturity = evergreen`) |

## Concretely

When complete, a reader can take any sentence of the form "the user feels X about Y" and decide correctly whether X belongs on the commitment layer or on the note state axes. For example:

- "The user wants this draft kept open for revision." → `review_state = draft`. This is NOT a commitment; it is artifact mutation posture.
- "The user owes a reply to Alice by Friday." → `Commitment` with `Waiting` or `Next Action` structure. This is NOT a `review_state` value and must not be written as one.
- "The user is unsure whether this note should be revised." → `review_state` posture question. NOT a commitment.
- "The user is unsure what the next step on the hiring project is." → commitment clarification (`Project` with an unresolved `Next Action`). NOT a note state question.

The contract must also forbid writing commitment meaning into legacy `review_state` values such as `promoted`, `processed`, or `inbox`. Those belong to compatibility migration, not to commitment semantics.

## Why This Matters

The user has exactly two levers of trust in a second brain: "the thing I wrote down is still editable in the right way" (state axes) and "the thing I owe is still being tracked" (commitments). When those are collapsed into one, the user cannot tell the difference between "this note is a draft" and "this responsibility is still open", and therefore cannot offload either burden confidently. The cognitive-prosthetic function dies quietly.

Concretely, flattening causes these failure modes:

- A user marks an open loop, the system stores `review_state = draft`, and the open loop silently loses its commitment meaning. The user cannot find "what I owe" anywhere, because they are looking for commitments and the system only has drafts.
- A user approves a note as reviewed; the system interprets it as "commitment done" and closes an unrelated open loop. The user loses trust immediately.
- A reviewer tool sweeps all `draft` notes; it unintentionally sweeps every open commitment too, because they were written into the same axis.

Each of these is a trust violation disguised as a data-model convenience. The contract in this file exists to prevent them at the architecture layer, before any schema is designed.

## Acceptance Criteria

- [ ] This file contains a "## What a note with review_state is" section that points to `docs/CONCEPTS/STATE_AXES_CONTRACT.md` without redefining it.
- [ ] This file contains a "## What a commitment is, and why it is not that" section with an explicit collision table covering at least the rows listed above.
- [ ] This file contains a "## Why flattening damages user trust" section written in user-recognizable terms, not in implementation terms.
- [ ] This file forbids writing commitment meaning into any `review_state` value (including legacy values such as `promoted`, `processed`, `inbox`).
- [ ] This file does not redefine `review_state` or `maturity` values.
- [ ] This file does not propose schema, tables, or event names.
- [ ] This file does not modify `STATE_AXES_CONTRACT.md` or `COMMITMENT_LAYER_CONTRACT.md`.

## How to Verify (Pre-Merge)

- Read this file side-by-side with `docs/CONCEPTS/STATE_AXES_CONTRACT.md`. Confirm nothing here redefines the canonical values of `review_state` or `maturity`.
- Read this file side-by-side with `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` §"Relation to state axes". Confirm the two docs agree.
- Apply the collision table to three sample user sentences and confirm the routing is unambiguous.
- Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` are touched.

## Out of Scope

- Defining commitment state transitions (see `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`).
- Defining the commitment vs execution-plan boundary (see `DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md`).
- Defining receipts (see `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`).
- Designing any storage, event, or migration for commitments.
- Modifying the promotion path or any `review_state` normalization code.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/NAME_THE_COMMITMENT_FAMILY.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (§Relation to state axes)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (§Delta 5)

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_VS_NOTE_STATE". Use the acceptance criteria above as the issue contract.
