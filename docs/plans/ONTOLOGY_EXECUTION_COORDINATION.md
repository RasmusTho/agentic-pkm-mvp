State: Plan (coordination contract for ontology-aligned execution across concurrent workstreams).

# Ontology Execution Coordination

## Purpose

This document exists to help multiple contributors, coding agents, or parallel workstreams continue
moving without drifting away from the current human-first semantics.

It does not redefine the ontology.
It is a development-time coordination document, not a runtime system-agent contract.
It defines:
- the reading path that should anchor further work,
- how aligned plans should continue rather than be abandoned,
- how to classify parallel work against the current forward line,
- and what should happen when an existing plan conflicts with the newer semantic baseline.

## Core rule

Meaning should flow in this order:
1. `docs/HUMAN-FLOWS.md`
2. `docs/CONCEPTS/USER_NEEDS_MODEL.md`
3. `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
4. `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
5. `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
6. `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
7. `docs/plans/USER_STORIES_AND_REQUIREMENTS.md`
8. `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`
9. architecture, runtime, schema, and implementation plans

Downstream documents may realize or constrain this meaning.
They must not silently redefine it.

## What should anchor new work

### For human/problem framing

Read:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`

### For context and semantic interpretation

Read:
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`

### For requirements and acceptance translation

Read:
- `docs/plans/USER_STORIES_AND_REQUIREMENTS.md`
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`

### For architecture-facing work

Also read:
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md`

## Parallel-work rule

Aligned work should continue.
It should not be abandoned merely because the semantic baseline has become clearer.

If an existing plan or initiative:
- supports the same human needs,
- does not flatten the newer context model,
- does not reintroduce ontology/implementation confusion,
- and can still satisfy the requirement and acceptance chain,

then it should be retained and relinked to the current document chain rather than discarded.

## What to do with older or parallel plans

### If a plan is aligned

- keep it active,
- update its references to the current concept and requirement documents,
- and treat it as an implementation or enablement path inside the newer semantic line.

### If a plan is partly aligned

- keep the useful parts,
- rewrite only the parts that still depend on superseded semantics,
- and record the narrower mismatch explicitly.

### If a plan conflicts materially

- do not continue it silently,
- name the conflict against the current human-function and ontology documents,
- and decide whether it belongs in:
  - current-state correction,
  - enablement,
  - or `v6.0` target-state work.

## Classification rule for concurrent work

Every substantial aligned work item should be classed as one of:

1. **Current-state correction**
   A fix to current docs, runtime behavior, or assumptions that already conflict with the accepted
   semantic line.

2. **Enablement**
   A smaller change that does not claim the full target state exists yet, but makes later alignment
   easier or safer.

3. **v6.0 target-state work**
   A larger design/architecture move that belongs in `docs/plans/V60_ARCHITECTURE_TARGET.md` before
   it is treated as present reality.

## Expected behavior from contributors and coding agents

When a contributor or coding agent touches semantics-adjacent areas such as:
- context,
- retrieval scope,
- archive exposure,
- artifact meaning,
- commitments,
- agent authority/accountability,
- paths/layout,
- architecture,
- or state axes,

it should make the following explicit in its reasoning or PR summary:
- which upstream human/ontology docs it treated as authoritative,
- whether the work is a current-state correction, enablement, or `v6.0` target-state step,
- and whether it is continuing an aligned plan or replacing a conflicting one.

## Non-goal

This document does not require all work to stop until the ontology pass is "finished".

The goal is narrower:
- keep work moving,
- keep good aligned plans alive,
- and stop silent drift back into implementation-first semantics.

## Related documents

- `docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md`
- `docs/plans/ONTOLOGY_STATUS_NEXT_DECISIONS.md`
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
