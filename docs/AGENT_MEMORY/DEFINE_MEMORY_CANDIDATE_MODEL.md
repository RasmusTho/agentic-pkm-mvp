---
name: Define Memory Candidate Model
description: Specify the candidate-memory shape that preserves provenance and review posture.
task_id: AGENT-MEMORY-01
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Lifecycle
parent_capability: Agent Memory
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# DEFINE_MEMORY_CANDIDATE_MODEL

## Purpose

Define the minimal model for memory candidates so observation does not silently become durable or
authoritative memory.

This task makes the contract's `Observe -> Candidate -> Review` boundary implementation-ready.

## What This Task Does

This task specifies the implementation contract for memory candidates. It defines:

- candidate identity and source provenance,
- memory class or proposed class,
- review state,
- inferred-vs-reviewed posture,
- and correction or contradiction hooks.

## Concretely

A later implementation should be able to represent a candidate memory with enough structure to say:

- what was observed,
- where it came from,
- what class it might become,
- whether it is inferred or reviewed,
- and whether it has been contradicted, revised, or rejected.

## Why This Matters

The concept contract explicitly rejects skipping from observation to truth. If the repository lacks
an explicit candidate model, any future memory runtime will be tempted to persist observations as if
they were settled knowledge.

## Acceptance Criteria

- [x] The implementation spec defines a candidate-memory model that preserves source provenance and
  explicit review state. Verify: `tests/agent_memory/test_memory_candidate_model.py::test_memory_candidate_preserves_source_and_review_state`
- [x] The candidate model distinguishes inferred material from reviewed material. Verify: `tests/agent_memory/test_memory_candidate_model.py::test_memory_candidate_marks_inferred_vs_reviewed`
- [x] The candidate model preserves proposed memory class without treating it as already promoted
  truth. Verify: `tests/agent_memory/test_memory_candidate_model.py::test_memory_candidate_separates_candidate_class_from_promoted_class`
- [x] The candidate model includes correction or contradiction posture strongly enough to support
  later revise/reject flows. Verify: `tests/agent_memory/test_memory_candidate_model.py::test_memory_candidate_supports_contradiction_and_revision_state`

## How to Verify (Pre-Merge)

- Add or update the candidate-model tests named in the acceptance criteria.
- Confirm the candidate shape does not require promotion before it can be stored or reviewed.
- Confirm provenance is first-class rather than optional note text.

## Out of Scope

- Review queue behavior.
- Promotion and rejection flows.
- Recall explanation surfaces.
- Write-authority guards.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`
- `docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md`

## Related GitHub Issues

Implemented by GitHub Issue #1079. Model shipped in `app/agent_memory/candidate.py`.
