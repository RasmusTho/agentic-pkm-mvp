State: Working memo on top of the active ontology-alignment pass.
Doc role: Status + decision memo
Authority: Non-authoritative consolidation of what is now established, what is partially realized in runtime, and which ontology decisions should be taken next.

# Ontology Status and Next Decisions

## Purpose

This memo captures the current ontology-alignment status in one place so the next decision phase is
explicit in the repo.

It does not redefine the ontology.
Its role is to summarize:
- what is now established,
- what has already been carried into runtime,
- what remains unresolved,
- and what order the next decisions should follow.

Primary concept sources:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`

Primary alignment and implementation notes:
- `docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md`
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md`
- `docs/plans/STATE_AXIS_SEPARATION_SPEC.md`

## Status summary

The system has now materially moved away from an overloaded `note` / `object` / `review` /
`promotion` vocabulary and toward a more explicit human-first ontology.

The most important established shifts are:
- the system is understood as a human-first, agent-assisted cognitive work landscape rather than
  only a note/object pipeline,
- `Vault Note` is treated as a distinct human artifact class rather than as only a generic runtime
  object,
- artifact and projection are treated as different kinds of thing,
- `review_state` and `maturity` are treated as different semantic axes,
- `promotion` is treated as a transition family rather than a single durable state value,
- and runtime `Plan` is treated as an `Execution Artifact`, not as the same thing as a human
  project, commitment, or review structure.

This is a real normalization step.
The repo is no longer relying as heavily on implementation-layer terms as if they were domain truth.

## What is now established

The following can be treated as the current normalized ontology core:
- `Human` and `System Agent` are distinct actor classes.
- `Vault Note` is a human-facing artifact class with special status in the warm plane.
- runtime objects, store rows, and index documents are projections or representations, not the
  artifact itself.
- `maturity` describes artifact standing, development, or durability.
- `review_state` describes review posture, mutation posture, or protection posture.
- `promotion` describes a transition family that may update one or more state axes.
- `Execution Plan` is runtime process structure, not the human commitment model.
- retrieval operates over projections and index documents, not over the full ontology directly.

## Runtime changes already aligned

The current runtime/code changes now carry this direction in several important places:
- evergreen is carried primarily by `maturity = evergreen`,
- review posture is derived separately from maturity,
- promotion to evergreen maps to `review_state = reviewed` instead of overloading
  `review_state = evergreen`,
- indexing accepts both canonical `maturity: evergreen` and legacy `review_state: evergreen`,
- and planner subplans preserve target intent instead of force-promoting everything to evergreen.

This means the ontology work is no longer only documentary.
It is already shaping runtime semantics and compatibility behavior.

## What remains open

The next ontology decisions still needed are:
- the final canonical value set for `review_state`,
- the final canonical value set for `maturity`,
- whether `promoted` should remain anywhere as a canonical value or be fully phased out,
- whether `Mirror Artifact` and `Receipt Artifact` should become distinct first-class implementation
  concepts,
- how human `Project`, `Commitment`, `Next Action`, `Waiting`, and `Review Cycle` should be modeled
  separately from planner execution plans,
- whether `source` should be split more strictly into epistemic artifact-role versus operational
  emitter/source attribution,
- and how much of the broader second-brain ontology should be implemented now versus documented as a
  later target model.

## Next decisions in recommended order

### 1. Finalize the state axes

Status:
- completed by `docs/CONCEPTS/STATE_AXES_CONTRACT.md`

First resolve the canonical contracts for:
- `review_state`
- `maturity`

The immediate output should be a short canonical state contract that answers:
- what each axis means,
- what question each axis answers,
- which values are canonical,
- which legacy values remain accepted temporarily,
- and which values are explicitly deprecated.

This is the most important next step because it unlocks controlled legacy reduction.

### 2. Define the human commitment layer

Status:
- completed by `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`

Next add a dedicated ontology/contract document for:
- `Project`
- `Commitment`
- `Next Action`
- `Waiting`
- `Review Cycle`

This is the largest remaining gap if the system is to function as a second-brain environment rather
than only as an artifact-and-transition system.

The key boundary to preserve is:
- human commitment structures are not the same thing as planner execution plans.

### 3. Sharpen the agent ontology

Status:
- completed by `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`

Then define the actor/accountability layer more explicitly around:
- `System Agent`
- `Agent Role`
- `Delegation`
- `Authority Boundary`
- `Receipt`
- accountability for automated action

This should make it clearer which runtime entities are true agents, which are roles, which are
tools/components, and how delegated action remains attributable.

### 4. Decide the mirror/receipt split

Status:
- completed by `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`

Then decide whether `Mirror Artifact` and `Receipt Artifact` should remain primarily ontological
distinctions or become separate first-class implementation concepts.

This matters because portability, explainability, and accountability are currently adjacent but not
cleanly separated in implementation language.

### 5. Perform controlled legacy reduction

Once the state-axis contract is fixed, begin phasing out mixed legacy forms where possible,
especially:
- new writes of `review_state: evergreen`,
- ambiguous uses of `promotion` as a field-like result instead of a transition family,
- and plan language that blurs execution artifacts with human commitment models.

Compatibility readers may remain longer than compatibility writers.

## Decision gate for the next pass

The next ontology pass should be considered complete only when all of the following exist in repo
form:
- a short canonical state-axis contract,
- a first commitment-layer ontology document,
- a sharper agent/delegation/accountability contract,
- and an explicit decision on mirror versus receipt implementation status.

Until then, the ontology direction is substantially improved but still incomplete.
