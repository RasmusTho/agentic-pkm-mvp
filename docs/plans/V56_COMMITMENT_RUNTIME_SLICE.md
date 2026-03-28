State: Plan (bounded v5.6-style enablement slice; not current runtime truth and not full v6 commitment realization).
Doc role: Plan
Authority: Defines the narrowest acceptable first commitment-runtime slice for forward-line enablement work. It does not override `docs/ARCHITECTURE.md` for current runtime truth, `docs/STATUS.md` for operational posture, or `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` for semantic ownership.
Owner: Forward-line architecture planning, downstream of `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` and `docs/HUMAN-FLOWS.md`
Last reviewed: 2026-03-22

# v5.6 Commitment Runtime Slice

## Purpose

This document defines the first bounded runtime slice for commitment support after the initial
state-axis separation wave.

Its job is to make the next enablement step explicit without pretending that the repo already has a
full commitment runtime.

The slice exists to answer one narrow planning question:
- what is the smallest runtime-support surface that can begin to treat commitments as first-class
  semantics without collapsing them into note state, artifact metadata, or execution plans?

## Why Now

The repo has already sharpened several semantic boundaries:
- artifact review posture is being separated from artifact standing,
- commitment semantics are now explicit in the ontology and human-flow documents,
- and the roadmap already points toward commitment-first modeling as a future bridge-build.

What is still missing is a bounded implementation-planning contract for the first runtime slice.
Without that contract, the next implementation step is likely to drift into one of three failure
modes:
- treating commitments as only note metadata,
- treating commitments as only planner/orchestrator execution plans,
- or postponing commitment support entirely until a much larger v6 architecture pass.

## Classification

This work is classified as:
- **Enablement**

It is not:
- a current-state bugfix,
- a declaration that commitment runtime already exists in the active baseline,
- or a full v6 target-state realization.

Reading rule:
- use this document to scope forward-line bridge work,
- not to reinterpret `docs/ARCHITECTURE.md` as if the slice were already implemented.

## Semantic Boundaries

The first commitment runtime slice must preserve the following distinctions.

### `Artifact`

Meaning:
- a meaning-bearing human-facing or retained thing that may support work, learning, reflection,
  or creation.

Rule:
- an artifact may support, represent, or refer to a commitment,
- but the artifact is not automatically the commitment itself.

### `Commitment`

Meaning:
- a responsibility structure such as an open loop, project, next action, waiting state, or review
  return.

Rule:
- commitment semantics must remain distinct from artifact state axes and from artifact maturity.

### `Execution Artifact`

Meaning:
- a generated runtime artifact such as a plan, subplan, or orchestration structure used to
  sequence system work.

Rule:
- execution artifacts may support commitment work,
- but they must not become the authoritative model of the human's commitments.

### `Receipt` and `Trace`

Meaning:
- receipts are human-legible accountability artifacts,
- traces are operational records used for coordination, audit, and reconstruction.

Rule:
- commitment-support actions may eventually need receipt-bearing surfaces,
- but this first slice must not require a new receipt store or event redesign.

## In-Scope First Slice

The first bounded slice should make room for runtime support of a small commitment family that is
already clearly justified by current repo semantics.

### In-scope commitment forms

The first slice may cover:
- `Open Loop`
- `Project Commitment`
- `Next Action`
- `Waiting State`
- `Review Return / Revisit Obligation`

### In-scope runtime intent

The first slice is allowed to support:
- distinguishing commitment-support structures from ordinary artifact state,
- preserving the difference between project structure and execution plans,
- making open-loop clarification and review return legible in runtime-facing planning,
- and creating room for future resurfacing and review support without requiring them yet.

### Minimal runtime shape

The first slice should be read as a bounded runtime-support layer, not a complete productivity
system.

Acceptable first-slice posture:
- runtime can identify or carry commitment-oriented structures as a semantic family,
- runtime can distinguish a commitment support structure from a vault note or retained artifact,
- runtime can distinguish a human next action from a tool call or planner step,
- and runtime can distinguish waiting/review-return obligations from generic inactivity.

This document intentionally does not define the exact storage or event shape for doing so.

## Out Of Scope

The following are explicitly out of scope for the first slice:
- a full commitment schema or table design,
- a comprehensive GTD engine,
- a planner/orchestrator redesign,
- a replacement of current artifact or note flows with commitment-native flows,
- a new receipt storage subsystem,
- a new event family or API contract redesign,
- relation-first overlap rollout in default runtime behavior,
- resurfacing as a default runtime capability,
- and any claim that the v6 commitment target is already realized.

## Runtime Posture

The first slice should begin as a bounded support capability in the forward line.

It may conceptually touch:
- runtime planning/orchestration boundaries where execution plans currently over-stand for human
  project structure,
- human-facing support surfaces where open loops, next actions, or waiting need to remain legible,
- review-oriented support paths where commitments need to return without being reduced to ranking,
- and accountability surfaces where commitment-relevant runtime actions may later need receipts.

It should not depend on:
- full schema redesign,
- full planner redesign,
- relation-first overlap rollout,
- resurfacing as default behavior,
- or a new default retrieval model.

## Guardrails And Non-Collapse Rules

The first slice must obey the following guardrails.

1. Commitment state must not be expressed as only `review_state` or `maturity`.
2. Commitment support must not be modeled as merely more note metadata on the writing surface.
3. Planner or orchestrator `Plan` objects must not be treated as the human's authoritative project
   or next-action structure.
4. Waiting must not collapse into generic inactivity, absence of action, or stale execution state.
5. Review return must not collapse into content approval, `review_state`, or retrieval ranking.
6. Commitment support must not require relation-first overlap semantics to be present in default
   runtime behavior.
7. Commitment support must not quietly turn salience or resurfacing heuristics into semantic
   authority.
8. Commitment-relevant accountability should remain compatible with the mirror/receipt distinction:
   traces may support the slice, but traces are not by themselves the receipt model.
9. The slice must remain compatible with the writing surface staying canonical for human-authored
   meaning.
10. Unknown or partial commitment structure must be a legal state; the runtime should not fabricate
    certainty just to satisfy a rigid model.

## Success Criteria

The first slice counts as successful when all of the following are true:
- the repo has an explicit runtime-facing place for commitment support that is not merely artifact
  state,
- open loop, project, next action, waiting, and review-return semantics are treated as a distinct
  semantic family,
- execution plans remain clearly subordinate to human commitment structure,
- current-state SoT docs do not need to pretend the full commitment runtime already exists,
- and future implementation work can proceed without re-arguing the artifact vs commitment vs plan
  distinction from scratch.

## Follow-On Sequencing

After the first bounded slice, later work may proceed in this order:

1. strengthen the runtime distinction between commitment-support structures and execution artifacts
2. connect review-return and open-loop pressure more explicitly to resurfacing experiments
3. define more concrete accountability expectations for commitment-relevant system actions
4. explore how commitment structures interact with richer context and overlap semantics
5. revisit fuller v6 commitment-runtime realization only after the bounded slice proves stable and
   non-collapsing

## Related Documents

- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/ROADMAP.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ONTOLOGY_RUNTIME_BRIDGE.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/plans/STATE_AXIS_SEPARATION_SPEC.md`
- `docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
