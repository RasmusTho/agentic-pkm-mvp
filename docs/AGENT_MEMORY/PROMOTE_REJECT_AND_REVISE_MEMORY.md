---
name: Promote Reject and Revise Memory
description: Specify explicit memory lifecycle decisions after review.
task_id: AGENT-MEMORY-03
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Review and promotion rules
parent_capability: Agent Memory
prerequisites: [AGENT-MEMORY-01, AGENT-MEMORY-02]
depends_on: [DEFINE_MEMORY_CANDIDATE_MODEL.md, ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md]
can_parallelize_with: []
---

# PROMOTE_REJECT_AND_REVISE_MEMORY

## Purpose

Specify the explicit lifecycle decisions that follow review so memory promotion, rejection, and
revision preserve provenance and do not silently rewrite history.

## What This Task Does

This task defines the implementation contract for post-review memory decisions. It specifies:

- what promotion means,
- what rejection means,
- what revision means,
- and what provenance and receipt linkage must survive each transition.

## Concretely

A later implementation should be able to:

- promote a reviewed candidate into a more durable memory class,
- reject a candidate without erasing the evidence trail,
- revise a candidate when the content or classification was partly right but incomplete,
- and preserve enough history to explain why the state changed.

## Why This Matters

The concept contract explicitly prefers correction through visibility rather than hidden
replacement. This task is where that posture becomes implementation-ready. Without it, promoted
memory can drift into opaque state and rejected memory can disappear without explanation.

## Acceptance Criteria

- [ ] Promotion is specified as preserving provenance and review context rather than copying only a
  final memory value. Verify: `tests/agent_memory/test_memory_promotion.py::test_promoted_memory_preserves_provenance`
- [ ] Rejection is specified as a visible lifecycle outcome rather than silent deletion of the
  candidate. Verify: `tests/agent_memory/test_memory_promotion.py::test_rejected_memory_preserves_review_receipt`
- [ ] Revision is specified as a correction path that can narrow or reclassify a candidate without
  erasing earlier evidence. Verify: `tests/agent_memory/test_memory_promotion.py::test_revised_memory_preserves_prior_context`
- [ ] Promotion into stronger knowledge posture is stricter than simple episodic retention. Verify: `tests/agent_memory/test_memory_promotion.py::test_semantic_promotion_requires_stricter_review_than_episodic_retention`

## How to Verify (Pre-Merge)

- Add or update the promotion-flow tests named in the acceptance criteria.
- Confirm lifecycle outcomes remain distinct in the model and receipts.
- Confirm revision does not silently overwrite provenance or source links.

## Out of Scope

- Candidate-memory modeling.
- Review queue submission logic.
- Recall explanation rendering.
- Runtime write-authority enforcement.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/AGENT_MEMORY/EXPLAIN_MEMORY_RECALL.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for promotion, rejection, and revision flows.
