---
name: Reconcile With v5.6 Commitment Runtime Slice
description: Read the v5.6 commitment runtime slice, state this v6 spec's position relative to it, and flag any terminology drift rather than silently resolving it
task_id: COMMITMENT-FIRST-CLASS-06
source_anchor: docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md
parent_capability: Commitments as a first-class semantic family
prerequisites: [COMMITMENT-FIRST-CLASS-01, COMMITMENT-FIRST-CLASS-02, COMMITMENT-FIRST-CLASS-03, COMMITMENT-FIRST-CLASS-04, COMMITMENT-FIRST-CLASS-05]
depends_on:
  - NAME_THE_COMMITMENT_FAMILY.md
  - DEFINE_COMMITMENT_VS_NOTE_STATE.md
  - DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md
  - DEFINE_COMMITMENT_STATE_TRANSITIONS.md
  - DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md
can_parallelize_with: []
---

State: Specification for the alignment task between this v6 commitment-first-class spec and the v5.6 commitment runtime slice. Docs-only; read-only against the v5.6 slice.

# Reconcile With v5.6 Commitment Runtime Slice

## Purpose

This is the key alignment task in this specification directory. It exists to make sure that (a) this v6.0 semantic spec and the v5.6 runtime-slice plan use compatible vocabulary, (b) the v5.6 slice is treated as the first enablement move and not as the target state, and (c) any disagreement between the two docs is named explicitly rather than quietly smoothed over. Silently resolving drift is not allowed: if the two docs say different things about the same concept, the disagreement is owned in this file until someone with authority decides which way to move.

## What This Task Does

Read `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` in full (without editing it) and, in this file, produce the following sections:

1. "## Position statement" — a short, clear statement that:
   - The v5.6 commitment runtime slice is the first runtime enablement move for commitment support.
   - This v6.0 spec describes the semantic target the v5.6 slice is a bridge toward.
   - This v6.0 spec is not a reinterpretation of the v5.6 slice, and the v5.6 slice is not a claim that the v6.0 target is realized.
   - Neither doc authorizes a rewrite of `docs/ARCHITECTURE.md` as if commitment runtime were complete.

2. "## Shared vocabulary" — list the terms that already agree across the two docs. Include at minimum:
   - `Commitment`
   - `Project` / `Project Commitment`
   - `Open Loop`
   - `Next Action`
   - `Waiting` / `Waiting State`
   - `Review Cycle` / `Review Return / Revisit Obligation`
   - `Execution Artifact`
   - `Artifact` vs `Commitment` distinction
   - The rule that commitment semantics must stay distinct from `review_state` and `maturity`

   State that these terms carry the same meaning in both docs and must continue to do so.

3. "## Known terminology drift (flagged, not resolved)" — list any place where the v5.6 runtime slice and this v6 spec use overlapping language differently. Flag each with: the term, what the v5.6 slice says, what this v6 spec says, and why the difference matters. Known drift points to examine at minimum:
   - `Open Loop` vs `open` as a commitment state. The v5.6 slice lists `Open Loop` as a commitment form. This v6 spec (in `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`) treats `open` as a state of a `Commitment`. These are related but not identical: "Open Loop" can describe either "a commitment that has not been clarified yet" or "any commitment that is not closed". Flag this distinction; do not collapse it.
   - `Review Return / Revisit Obligation` (v5.6) vs `Review Cycle` (this spec, matching `COMMITMENT_LAYER_CONTRACT.md`). The v5.6 slice uses both phrasings around review semantics. This v6 spec uses `Review Cycle` as the anchor. Flag the phrasing difference and state that `Review Cycle` is the authoritative v6 name while acknowledging that `Review Return` / `Revisit Obligation` in the v5.6 slice refer to the same underlying concept.
   - `Receipt` handling. The v5.6 slice explicitly forbids requiring a new receipt store. This v6 spec (in `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`) also forbids prescribing a new receipt store but requires that commitment transitions be receipt-bearing. These are compatible but subtle; flag the boundary: the v6 spec does not require a new store, it requires that whatever receipt lane exists eventually carries commitment-transition receipts.
   - `Waiting` vs `blocked`. The v5.6 slice treats `Waiting State` as one in-scope commitment form and separately warns that waiting must not collapse into generic inactivity. This v6 spec (in `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`) introduces `blocked` as a distinct state from `waiting`. Flag that `blocked` is not yet in the v5.6 slice vocabulary; the v6 spec intentionally extends the state family, and the v5.6 runtime implementation does not need to carry `blocked` in its first slice.
   - `Execution Artifact` vs `Plan`. Both docs treat execution plans as distinct from commitments. No drift here, but confirm the agreement in writing so future edits do not accidentally introduce drift.

   For each flagged item, the section must end with: "Resolution owner: the implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally."

4. "## Non-contradictions to preserve" — list at least the following hard invariants that must not drift in either direction:
   - Commitment state must not be expressed only as `review_state` or `maturity` (v5.6 Guardrail 1; v6 spec `DEFINE_COMMITMENT_VS_NOTE_STATE.md`).
   - Planner `Plan` objects must not be treated as the user's authoritative project or next-action structure (v5.6 Guardrail 3; v6 spec `DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md`).
   - Waiting must not collapse into generic inactivity (v5.6 Guardrail 4).
   - Review Return / Review Cycle must not collapse into content approval or `review_state` (v5.6 Guardrail 5; v6 spec `DEFINE_COMMITMENT_VS_NOTE_STATE.md`).
   - Unknown / partial commitment structure is a legal state (v5.6 Guardrail 10; v6 spec `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`).
   - Commitment support must not require a new receipt store (v5.6 Out Of Scope; v6 spec `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`).

   State that any future edit to either doc that violates these invariants is a drift event that must be caught in review.

5. "## What this reconcile does NOT do" — state the boundaries:
   - Does not edit `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`.
   - Does not resolve any flagged drift unilaterally.
   - Does not claim the v6 semantic target is realized.
   - Does not propose runtime changes.
   - Does not reopen schema or event design.

## Concretely

When complete, a reader can open this file and in under five minutes understand:

- Which terms are safe to use interchangeably between the v5.6 slice and this v6 spec.
- Which terms carry subtle differences that must not be smoothed over.
- Which hard invariants are shared by both docs and must be defended in every future edit.
- Who owns the resolution of any outstanding drift (answer: the implementation lane, not this spec).

## Why This Matters

The single most common failure mode for a two-doc architecture story is that the runtime doc and the semantic doc drift apart over time and neither lane notices until an implementation disagreement forces the issue. By that point, one of the two docs is usually rewritten under pressure, and whichever doc was less formal loses. The commitment layer is especially vulnerable to this because the v5.6 slice is narrow (deliberately) and the v6 spec is broader (deliberately), and it is easy to assume they mean the same thing by the same word.

This reconcile task is the architectural defense against quiet drift. By naming disagreements instead of hiding them, it keeps the user's cognitive-prosthetic trust story coherent across the bridge from v5.6 to v6.

## Acceptance Criteria

- [ ] `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` has been read in full by the author of this file. No edits were made to it.
- [ ] This file contains a "## Position statement" section naming the v5.6 slice as the first enablement move and this v6 spec as the semantic target.
- [ ] This file contains a "## Shared vocabulary" section listing the terms that agree across both docs.
- [ ] This file contains a "## Known terminology drift (flagged, not resolved)" section that names each drift point, what each doc says, and who owns resolution.
- [ ] This file contains a "## Non-contradictions to preserve" section listing the hard invariants shared by both docs.
- [ ] This file contains a "## What this reconcile does NOT do" section stating the boundaries explicitly.
- [ ] This file does not edit or propose edits to `V56_COMMITMENT_RUNTIME_SLICE.md`.
- [ ] This file does not resolve any flagged drift on its own authority.
- [ ] This file does not propose schema, events, or runtime changes.

## How to Verify (Pre-Merge)

- Read this file side-by-side with `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`. Confirm every claim in the "Shared vocabulary" section is actually supported by the v5.6 doc.
- Read this file side-by-side with the other five task files in this directory. Confirm that every flagged drift point references a real section in one of the task files plus a real section in the v5.6 slice.
- Confirm the "Non-contradictions to preserve" list matches the v5.6 slice's Guardrails section.
- Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` are touched.

## Out of Scope

- Editing `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` in any way.
- Resolving flagged drift. (Resolution is an implementation-lane concern and belongs wherever the v5.6 slice is picked up.)
- Proposing a new architecture pillar or delta.
- Modifying `COMMITMENT_LAYER_CONTRACT.md` or `V60_ARCHITECTURE_TARGET.md`.
- Any code, schema, or runtime change.
- Creating GitHub issues.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/NAME_THE_COMMITMENT_FAMILY.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_VS_NOTE_STATE.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (read-only reference)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (§Pillar 5, §Delta 5)
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/RECONCILE_WITH_V56_COMMITMENT_SLICE". Use the acceptance criteria above as the issue contract. Resolution of any flagged drift belongs on the issue that actually implements the v5.6 slice, not on this reconcile issue.
