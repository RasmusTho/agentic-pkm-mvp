---
name: Define Commitment Receipt Requirement
description: Require that each commitment state transition leave a receipt the user can trust; cross-reference the persistence-surface receipt lane without prescribing it
task_id: COMMITMENT-FIRST-CLASS-05
source_anchor: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Relation to artifacts
parent_capability: Commitments as a first-class semantic family
prerequisites: [COMMITMENT-FIRST-CLASS-01]
depends_on: [NAME_THE_COMMITMENT_FAMILY.md]
can_parallelize_with: [DEFINE_COMMITMENT_VS_NOTE_STATE, DEFINE_COMMITMENT_VS_EXECUTION_PLAN, DEFINE_COMMITMENT_STATE_TRANSITIONS]
---

State: Specification for the commitment-receipt requirement in the v6.0 commitment-first-class capability. Docs-only.

# Define Commitment Receipt Requirement

## Purpose

This task requires that each commitment state transition leave a receipt the user can trust. It exists because the cognitive-prosthetic value of the system depends not only on *carrying* commitments (the externalization need) but also on making commitment changes *inspectable after the fact* (the trust need). Without receipts, explainability (defined in `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`) cannot be honored, because there is nothing to look at later.

This task does NOT design the receipt storage surface, schema, or format. It states the requirement and cross-references the persistence-surface receipt lane that the v6.0 architecture target already distinguishes.

## What This Task Does

Write three contract sections in this file:

1. "## What a commitment receipt is" — a short user-facing definition:
   - A commitment receipt is an accountability artifact that records a single commitment state transition in user-legible terms.
   - It must be able to answer at least: which commitment, which transition (before → after), when, and why (user action, review cycle, external trigger, accepted suggestion).
   - It is a **receipt**, not a log row. It exists to restore the user's trust, not to debug the system.

2. "## Where receipts live (cross-reference only)" — a pointer to the persistence-surface receipt lane without prescribing it:
   - The v6.0 architecture target distinguishes writing, retention, and system surfaces (`V60_ARCHITECTURE_TARGET.md` §Pillar 4). Receipts belong to the system surface, NOT to the writing surface and NOT to the retention surface. Commitment receipts are not notes in the vault.
   - The persistence-surface receipt lane is owned elsewhere (receipt and trace distinctions are developed in `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` and `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`). This spec does not duplicate, replace, or prescribe that design. It simply states that commitment transitions are receipt-bearing events that must flow into whatever receipt lane the architecture settles on.
   - This spec also does not prescribe a new receipt store. The v5.6 commitment runtime slice explicitly says the first slice must not require a new receipt store. Commitment receipts may initially live in whatever receipt-bearing surface the architecture already has.

3. "## Trust properties receipts must support" — the list of properties the receipt lane must satisfy for commitments:
   - **Inspectable.** The user can find and read the receipt for any commitment transition.
   - **Attributable.** Each receipt names the cause of the transition (user, review cycle, external trigger, accepted system suggestion). System-originated transitions must be clearly marked as system-originated.
   - **Non-fabricated.** If the system does not know the cause, the receipt must say so, not guess.
   - **Non-displacing.** Receipts are not the commitment itself. A missing receipt is a trust bug; a missing commitment is a different bug. Receipts must not silently become the authoritative model of the commitment.
   - **Trace-compatible but not identical to a trace.** Traces are operational records for coordination and debugging; receipts are human-legible accountability artifacts. Commitment receipts may be derivable from traces but must not be confused with them (see `COMMITMENT_LAYER_CONTRACT.md` and `MIRROR_RECEIPT_DECISION.md`).

## Concretely

When complete, a reader can take a sample commitment transition and describe the receipt requirement in user-facing terms. Example:

> The user marks the "reply to Alice" commitment as `done` on Wednesday. A receipt is produced recording: commitment = "reply to Alice", before = `next`, after = `done`, time = Wednesday 14:03, cause = "user marked complete". The receipt lives on the system surface. If the user later asks "when did I close that?", the system can answer from the receipt. If the user later asks "did the system close this automatically?", the receipt's attribution field gives an honest answer.

The spec must also state explicitly that receipts for commitment transitions must not be stored on the writing surface (i.e., not as vault notes) and must not be used as a substitute for the commitment itself.

## What a commitment receipt is

A commitment receipt is an accountability artifact that records a single commitment state transition in user-legible terms.

A receipt must be able to answer at least these questions:
- which commitment is this about?
- what changed (before → after state)?
- when did the transition occur?
- why did the transition happen (user action, review cycle, external trigger, or accepted system suggestion)?

A commitment receipt is a **receipt**, not a log row or internal trace.

Its purpose is to restore the user's trust in the system by making commitment changes inspectable after the fact. A receipt exists so the user can later understand what happened to a commitment, not so the system can debug its own internals.

Examples of receipts:
- "Marked 'reply to Alice' as done on Wednesday 14:03 (user action)"
- "Moved 'quarterly planning' to waiting on 2026-04-12 (external trigger: budget decision deferred)"
- "System suggested closing 'follow up on feedback'; user confirmed on 2026-04-11"

## Where receipts live (cross-reference only)

Commitment receipts belong on the **system surface**, not on the writing surface and not on the retention surface.

This distinction is explained in `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4 (persistence surfaces). The v6.0 architecture target distinguishes three persistence surfaces:
- **writing surface** — human-authored editable artifacts (vault notes)
- **retention surface** — retained source-rich artifacts kept for retrieval and reuse
- **system surface** — mirrors, indexes, traces, receipts, execution artifacts, and runtime support structures

Commitment receipts are **not vault notes**. They do not live on the writing surface.

The specific design of the receipt storage model, schema, and retrieval path is owned by the persistence-surface receipt lane, documented in:
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` — the decision that receipts are distinct from mirror artifacts
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` — the distinction between receipts, traces, and audit records

This spec does not duplicate, replace, or prescribe that design. It simply establishes that commitment state transitions are **receipt-bearing events** that must flow into whatever receipt lane the architecture settles on.

**Importantly:** This spec does not require a new receipt storage system. The v5.6 commitment runtime slice (documented in `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` §Out Of Scope, §Guardrail 8) explicitly states that the first commitment slice must not require a new receipt store. Commitment receipts may initially live in whatever receipt-bearing surface the architecture already has. The requirement here is only that commitment transitions are receipt-bearing events, not that a new storage layer must be invented to hold them.

## Trust properties receipts must support

For commitment receipts to restore user trust, they must support all of the following properties:

### Inspectable

The user must be able to find and read the receipt for any commitment state transition.

When a user asks "when did I close the hiring project?", the system can answer by retrieving the receipt. The receipt must be discoverable without requiring the user to reconstruct state from raw logs or traces.

### Attributable

Each receipt must name the cause of the transition. The receipt must make clear whether the transition came from:
- **user action** — the user explicitly marked the commitment, rescheduled it, or changed it
- **review cycle** — the transition happened as part of a periodic review
- **external trigger** — the transition was triggered by an external event (deadline met, dependency resolved, decision arrived)
- **accepted system suggestion** — the system suggested a change and the user confirmed it

System-originated transitions must be clearly marked as system-originated. If the transition happened automatically under standing policy or delegation, that policy and its basis must be identifiable from the receipt.

### Non-fabricated

If the system does not know the cause of a transition, the receipt must **say so**, not guess.

Example: "User marked 'review hiring results' as waiting; reason not recorded" is a better receipt than the system guessing "user action" when it was actually triggered by an automation the user forgot about.

### Non-displacing

Receipts are not the commitment itself.

A missing receipt is a trust bug. A missing commitment is a different bug. Receipts must not silently become the authoritative model of the commitment. The commitment itself remains the source of truth; receipts are accountability artifacts that document its history.

Corollary: if all receipts for a commitment are lost, the commitment's current state and identity must still be retrievable. The commitment is not dependent on its receipts for existence.

### Trace-compatible but not identical to a trace

Commitment receipts may be derivable from, or correlated with, operational traces. Traces are essential for runtime coordination, debugging, and reconstruction.

However, receipts are **human-legible accountability artifacts**, and traces are **machine-usable operational records**. These are different kinds of things:
- a trace may be partial, noisy, or optimized for runtime efficiency
- a receipt must be legible and sufficient for accountability
- a trace exists for the system to coordinate itself; a receipt exists for the human to understand what happened

Commitment receipts must not be confused with raw event streams or operational logs even when they are derived from them (see `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §Receipt vs Trace).

## Why This Matters

Explainability without receipts is a promise that cannot be kept. The user may trust the system's commitment handling on day one, but trust depends on being able to look back. If a commitment transition leaves no durable trace, the user is effectively being asked to trust the system's memory — which is exactly the cognitive load the second brain was supposed to remove.

Concretely, missing receipts cause these failure modes:

- The user asks "what happened to the hiring project last week?" and gets no answer, because the transitions were never recorded as receipts.
- The system claims a commitment was closed; the user cannot verify the cause; trust collapses.
- Receipts are conflated with notes; the writing surface fills up with system-authored receipt noise; the vault stops feeling like the user's own space.
- Receipts are conflated with raw traces; the user cannot find user-legible accountability because everything is buried in operational logs.

Each of these is a trust violation. The receipt requirement in this file exists so that explainability (from `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`) has something concrete to stand on, without this spec prescribing the receipt store itself.

## Acceptance Criteria

- [x] This file contains a "## What a commitment receipt is" section defining the receipt in user-facing terms (what it records, what it is for).
- [x] This file contains a "## Where receipts live (cross-reference only)" section that points to `V60_ARCHITECTURE_TARGET.md` §Pillar 4 (persistence surfaces) and to `MIRROR_RECEIPT_DECISION.md` / `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` without duplicating or replacing them.
- [x] This file explicitly states that commitment receipts belong on the system surface, not on the writing surface, and are not vault notes.
- [x] This file contains a "## Trust properties receipts must support" section covering inspectability, attribution, non-fabrication, non-displacement, and trace-compatibility.
- [x] This file explicitly states that this spec does NOT prescribe a new receipt store, consistent with `V56_COMMITMENT_RUNTIME_SLICE.md`'s out-of-scope rule.
- [x] This file does not design any schema, event, or data format for receipts.
- [x] This file does not modify `MIRROR_RECEIPT_DECISION.md`, `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, or `COMMITMENT_LAYER_CONTRACT.md`.

## How to Verify (Pre-Merge)

- [x] Read this file side-by-side with `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` and `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`. Confirm the cross-references are accurate and non-duplicative.
- [x] Read this file side-by-side with `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` §Out Of Scope. Confirm this spec does not require a new receipt store.
- [x] Read this file side-by-side with `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4 and §Pillar 9. Confirm the surface placement is compatible.
- [x] Apply the trust-property list to a sample commitment-transition scenario and confirm the properties are sufficient to restore the user's trust.
- [x] Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` are touched.

## Out of Scope

- Designing the receipt storage format, schema, event name, or API.
- Creating a new receipt store, surface, or lane.
- Modifying any existing receipt or trace handling in the runtime.
- Implementing commitment transitions themselves.
- Resurfacing commitments or building review-return surfacing.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (§Pillar 4, §Pillar 9, §Delta 9)
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (§Out Of Scope, §Guardrail 8)

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_RECEIPT_REQUIREMENT". Use the acceptance criteria above as the issue contract.
