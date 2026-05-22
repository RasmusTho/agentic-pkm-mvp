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

`app/agent_memory/promotion.py` implements the post-review lifecycle decisions:

- `promote(entry)` — promotes a reviewed candidate, producing a `PromotedMemory` with
  `outcome=ACCEPTED` and full provenance embedded.
- `reject(entry)` — records a visible rejection, producing a `PromotedMemory` with
  `outcome=REJECTED`; the candidate is retained, not deleted.
- `revise(original_entry, revised_entry)` — records a correction, producing a `PromotedMemory`
  with `outcome=REVISED`; earlier evidence is preserved and the correction chain is traceable.
- `PromotedMemory` — the immutable receipt type that preserves provenance and review context
  across all three outcomes.

## Why This Matters

The concept contract explicitly prefers correction through visibility rather than hidden
replacement. This task is where that posture becomes implementation-ready. Without it, promoted
memory can drift into opaque state and rejected memory can disappear without explanation.

## Acceptance Criteria

- [x] Promotion is specified as preserving provenance and review context rather than copying only a
  final memory value. Verify: `tests/agent_memory/test_memory_promotion.py::test_promoted_memory_preserves_provenance`
- [x] Rejection is specified as a visible lifecycle outcome rather than silent deletion of the
  candidate. Verify: `tests/agent_memory/test_memory_promotion.py::test_rejected_memory_preserves_review_receipt`
- [x] Revision is specified as a correction path that can narrow or reclassify a candidate without
  erasing earlier evidence. Verify: `tests/agent_memory/test_memory_promotion.py::test_revised_memory_preserves_prior_context`
- [x] Promotion into stronger knowledge posture is stricter than simple episodic retention. Verify: `tests/agent_memory/test_memory_promotion.py::test_semantic_promotion_requires_stricter_review_than_episodic_retention`

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

Implemented by #1081.
