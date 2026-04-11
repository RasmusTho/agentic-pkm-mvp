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

---

## Position Statement

The v5.6 commitment runtime slice (documented in `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`) represents the **first bounded enablement move** for commitment support in the forward-line runtime. This v6.0 capability specification describes the **semantic target architecture** that the v5.6 slice is a bridge toward — a commitment-first modeling layer where projects, next actions, waiting states, and review cycles remain distinct from artifact lifecycle, note maturity, and execution-plan vocabulary.

This v6.0 spec is **not a reinterpretation** of the v5.6 slice. The v5.6 slice is not a claim that the v6.0 target is already realized. Rather, the two documents serve different purposes:
- **v5.6 slice:** Defines the narrowest acceptable runtime surface to begin treating commitments as first-class (without full schema redesign, planner overhaul, or new receipt stores).
- **v6.0 spec:** Defines the semantic boundaries, state vocabulary, and receipt requirements that the v5.6 slice is designed to eventually support.

Neither document authorizes rewriting `docs/ARCHITECTURE.md` as if commitment runtime support were complete. The v5.6 slice is an enablement step, not a realization of the full v6.0 target.

## Shared Vocabulary

The following terms appear in both the v5.6 commitment runtime slice and this v6.0 capability specification and carry the same semantic meaning in both documents. These terms must remain interchangeable across the two docs and must not drift:

- **`Commitment`** — A responsibility structure (open loop, project, next action, waiting state, or review return) that the user experiences as requiring attention, maintenance, progress, decision, follow-up, or closure. Both docs treat this as the umbrella concept.
- **`Project` / `Project Commitment`** — A commitment that requires multiple steps over time. Both docs distinguish projects from single next actions and from artifact structure.
- **`Open Loop`** — An unresolved commitment or clarification point. Both docs treat open loops as in-scope commitment forms requiring runtime support.
- **`Next Action`** — The next concrete step that can advance a commitment or project. Both docs distinguish next actions from planner steps, tool calls, or artifact review actions.
- **`Waiting` / `Waiting State`** — A commitment state where progress depends on another actor, another event, or a future condition. Both docs forbid collapsing waiting into generic inactivity.
- **`Review Cycle` / `Review Return` / `Revisit Obligation`** — A recurring re-orientation practice (or the obligation it creates) that restores trust in the commitment landscape. Both docs treat review as a first-class commitment concern, not as content approval or `review_state` metadata.
- **`Execution Artifact`** — A generated runtime artifact (plan, subplan, orchestration step) used to sequence system work. Both docs treat execution artifacts as distinct from commitments and subordinate to human commitment structure.
- **`Artifact` vs `Commitment` distinction** — Both docs require that an artifact may represent or support a commitment, but the artifact is not automatically the commitment itself. A note may carry commitment meaning, but the note's lifecycle is not the commitment's state.
- **Commitment semantics must remain distinct from `review_state` and `maturity`** — Both docs require that commitment state is not expressed as only `review_state` values or `maturity` labels (v5.6 Guardrail 1; v6 spec §DEFINE_COMMITMENT_VS_NOTE_STATE).

These terms are the architectural common ground between the two documents. Any future edit to either doc that redefines or collides with these shared meanings is a drift event that must be caught in review.

## Known Terminology Drift (Flagged, Not Resolved)

The following are places where the v5.6 runtime slice and this v6.0 spec use related or overlapping language with subtle differences. Each drift point is named below with its context, the reason the difference matters, and the owner of eventual resolution. **No drift is resolved in this file.** This section exists to keep the user's cognitive story coherent across the bridge from v5.6 to v6.0 by naming disagreements instead of hiding them.

### Drift Point 1: `Open Loop` vs `open` as a Commitment State

**The v5.6 slice says:** "Open Loop" is listed as an in-scope commitment form (§In-scope commitment forms). The slice treats "Open Loop" as a recognizable commitment category at runtime.

**This v6.0 spec says:** `open` is one of five states a commitment occupies (§DEFINE_COMMITMENT_STATE_TRANSITIONS.md). A commitment in the `open` state is one where the commitment exists and is active but has no clarified next action yet.

**Why the difference matters:** "Open Loop" in the v5.6 slice can mean either "a commitment that has not been clarified yet" (mapping to v6's `open` state) or "any commitment that is not closed" (a broader category). The v6.0 spec intentionally narrows "open" to mean specifically "unresolved/unclarified." A commitment can move from `open` to `next` (when a next action is clarified), to `waiting` (when an external dependency is recognized), or to `blocked` (when an impediment is named). This distinction is subtle but consequential for runtime signaling.

**Resolution owner:** The implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally.

### Drift Point 2: `Review Return` / `Revisit Obligation` vs `Review Cycle`

**The v5.6 slice says:** Review semantics are expressed as "Review Return" and "Revisit Obligation" (§In-scope commitment forms and §Guardrails). Both phrasings appear in the slice's vocabulary.

**This v6.0 spec says:** `Review Cycle` is the authoritative name for this commitment concern (matching `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`). The v6 spec treats review as a recurring re-orientation practice that restores trust in the commitment landscape.

**Why the difference matters:** "Review Return" and "Revisit Obligation" emphasize the return-from-somewhere aspect; "Review Cycle" emphasizes the regular-practice aspect. Both capture the same underlying concept (a commitment requiring periodic re-examination), but the naming difference reflects a subtle perspective shift from "getting back to this" (v5.6 frame) to "keeping this in trust through regular re-examination" (v6 frame). Runtime UI and notification logic may treat these perspectives differently.

**Resolution owner:** The implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally.

### Drift Point 3: `Receipt` Handling

**The v5.6 slice says:** Commitment support must not require a new receipt store or event redesign (§Out Of Scope). The first slice must work with existing receipt-bearing surfaces if they exist.

**This v6.0 spec says:** Commitment state transitions must be receipt-bearing (§DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md). Each transition must leave a durable, inspectable, attributable record that the user can trust. The spec does NOT prescribe a new receipt store; it requires that whatever receipt lane exists eventually carries commitment-transition receipts.

**Why the difference matters:** These are compatible but subtle. The v5.6 slice prohibits creating new infrastructure; the v6.0 spec requires that transitions are accountable. The boundary is this: the v6 spec does not require a new store, but it does require that commitment transitions flow into whatever receipt lane the architecture settles on. If the v5.6 slice lands in an implementation lane that has no receipt lane yet, that is a gap the forward-line implementation must address — but it is not a conflict with this spec.

**Resolution owner:** The implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally.

### Drift Point 4: `Waiting` vs `blocked`

**The v5.6 slice says:** `Waiting State` is one in-scope commitment form (§In-scope commitment forms). The slice warns that waiting must not collapse into generic inactivity (§Guardrails, item 4).

**This v6.0 spec says:** `blocked` is a distinct commitment state from `waiting` (§DEFINE_COMMITMENT_STATE_TRANSITIONS.md). `Waiting` means progress depends on another actor, event, or future condition (expected external dependency). `Blocked` means progress is stalled by something unresolved (impediment). These are related but distinct: both are "not next", but waiting has a clear expected condition, while blocked does not.

**Why the difference matters:** The v5.6 slice does not distinguish these two cases; it treats waiting as a single commitment form. The v6 spec intentionally extends the state family to name the blockage case separately. This distinction is not a contradiction of the v5.6 slice; it is an intentional refinement. The v5.6 runtime implementation does not need to carry `blocked` in its first slice (waiting is sufficient to cover both cases initially), but future extensions will need to clarify the boundary.

**Resolution owner:** The implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally.

### Drift Point 5: `Execution Artifact` vs `Plan` (Agreement)

**The v5.6 slice says:** Execution artifacts (plans, subplans, orchestration steps) are explicitly distinct from commitments (§Semantic Boundaries). The slice forbids treating planner `Plan` objects as the user's authoritative project or next-action structure (§Guardrails, item 3).

**This v6.0 spec says:** Execution artifacts and commitments occupy separate semantic layers (§DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md). A commitment is a human responsibility structure; an execution plan is a system process structure. Plans may support commitment work, but they do not replace or supersede commitments.

**Why the difference matters:** There is no drift here. Both docs agree on the boundary and the direction of causality: commitments are primary, execution plans are secondary. This agreement is stated explicitly to prevent future edits from accidentally introducing confusion (e.g., auto-closing a commitment because an execution plan finished, or treating a planner step as if it were a next action).

**Resolution owner:** The implementation lane where the v5.6 slice lands. This spec does not resolve the drift unilaterally.

## Non-Contradictions to Preserve

The following are hard invariants that appear in both the v5.6 commitment runtime slice and this v6.0 capability specification. Any future edit to either document that violates these invariants is a drift event and must be caught in review. Reviewers of either document should flag any change that threatens these non-contradictions.

1. **Commitment state must not be expressed only as `review_state` or `maturity`** (v5.6 Guardrail 1; v6 spec §DEFINE_COMMITMENT_VS_NOTE_STATE.md). Commitment semantics are orthogonal to artifact review posture and durability. A note with `review_state = draft` is not automatically an open commitment; a commitment in the `open` state is not automatically an artifact in `review_state = draft`.

2. **Planner `Plan` objects must not be treated as the user's authoritative project or next-action structure** (v5.6 Guardrail 3; v6 spec §DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md). Commitments are user-owned responsibility structures; execution plans are system-owned process structures. The user's project structure is authoritative; planner projects are tools to help advance user projects.

3. **Waiting must not collapse into generic inactivity** (v5.6 Guardrail 4; v6 spec §DEFINE_COMMITMENT_STATE_TRANSITIONS.md). A waiting commitment is an active waiting — a commitment to a future condition or another actor's action — not a note that happens to have no recent activity.

4. **Review Return / Review Cycle must not collapse into content approval or `review_state`** (v5.6 Guardrail 5; v6 spec §DEFINE_COMMITMENT_VS_NOTE_STATE.md). Review as a commitment concern is about re-orienting to and reaffirming the landscape of responsibility, not about approving artifact changes or marking notes as reviewed.

5. **Unknown / partial commitment structure is a legal state** (v5.6 Guardrail 10; v6 spec §DEFINE_COMMITMENT_STATE_TRANSITIONS.md). The runtime must not fabricate certainty about a commitment's state, family, or next steps. `unknown` or `uncertain` is a valid operational state, not a temporary placeholder.

6. **Commitment support must not require a new receipt store** (v5.6 Out Of Scope; v6 spec §DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md). The first slice can integrate with existing receipt-bearing surfaces. New receipt infrastructure belongs downstream, not in the first slice.

All six of these invariants are architectural guardrails. Changing any of them is a major decision that belongs in the implementation lane, not in incremental spec edits.

## What This Reconcile Does NOT Do

To keep scope boundaries clear:

- **Does not edit `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md`.** The v5.6 slice is read-only for this task. All changes stay within `docs/COMMITMENT_AS_FIRST_CLASS/` unless explicitly authorized elsewhere.
- **Does not resolve any flagged drift unilaterally.** This file names disagreements for visibility; it does not declare winners. Resolution belongs to the implementation lane.
- **Does not claim the v6 semantic target is realized.** This spec describes the target architecture. Realizing it is downstream work.
- **Does not propose runtime changes.** All sections in this file are documentation-only. No code, schema, event design, or stored-procedure changes are included.
- **Does not reopen schema or event design.** Both the v5.6 slice and this spec deliberately avoid prescribing storage shape. That work is downstream.

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
