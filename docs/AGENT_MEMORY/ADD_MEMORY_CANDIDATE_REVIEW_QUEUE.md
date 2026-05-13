---
name: Add Memory Candidate Review Queue
description: Specify the review surface that prevents candidate memory from becoming hidden truth.
task_id: AGENT-MEMORY-02
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Review and promotion rules
parent_capability: Agent Memory
prerequisites: [AGENT-MEMORY-01]
depends_on: [DEFINE_MEMORY_CANDIDATE_MODEL.md]
can_parallelize_with: []
---

# ADD_MEMORY_CANDIDATE_REVIEW_QUEUE

## Purpose

Specify the review queue or equivalent review surface that makes candidate-memory decisions explicit
before promotion.

## What This Task Does

This task defines the implementation contract for a review queue. It specifies:

- how candidate memories enter review,
- what decision states the queue must support,
- what provenance and explanation must remain visible during review,
- and what human or policy decision boundary must exist before promotion.

## Concretely

A later implementation should be able to present candidate memories for review with:

- candidate content,
- source and provenance,
- inferred or reviewed posture,
- proposed memory class,
- and decision actions such as promote, reject, or revise.

## Why This Matters

The concept contract requires candidate material to be checked by human review, policy, or stronger
evidence before promotion. A review queue is how that rule becomes operational rather than
aspirational.

## Acceptance Criteria

- [ ] The implementation spec requires candidate memories to pass through a review queue or
  equivalent explicit review surface before promotion. Verify: `tests/agent_memory/test_memory_candidate_review_queue.py::test_review_queue_requires_human_decision`
- [ ] The review surface preserves source provenance, review posture, and proposed memory class for
  each candidate. Verify: `tests/agent_memory/test_memory_candidate_review_queue.py::test_review_queue_exposes_candidate_provenance_and_class`
- [ ] The review surface supports promote, reject, and revise as separate review outcomes. Verify: `tests/agent_memory/test_memory_candidate_review_queue.py::test_review_queue_supports_promote_reject_and_revise`
- [ ] The review surface does not let unreviewed candidates be treated as recalled authoritative
  memory by default. Verify: `tests/agent_memory/test_memory_candidate_review_queue.py::test_review_queue_does_not_authorize_unreviewed_recall`

## How to Verify (Pre-Merge)

- Add or update the review-queue tests named in the acceptance criteria.
- Confirm review decisions are explicit state transitions, not implicit side effects of recall.
- Confirm the queue remains inspectable enough for a human to understand why a candidate is there.

## Out of Scope

- Candidate-memory data modeling.
- Promotion storage semantics after decision.
- Recall explanation rendering.
- Write-authority enforcement after recall.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/AGENT_MEMORY/DEFINE_MEMORY_CANDIDATE_MODEL.md`
- `docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for review-queue behavior.
