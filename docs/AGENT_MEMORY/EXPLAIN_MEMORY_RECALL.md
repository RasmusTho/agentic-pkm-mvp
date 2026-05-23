---
name: Explain Memory Recall
description: Specify how recalled memory remains explainable to the human.
task_id: AGENT-MEMORY-04
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Relation to receipts
parent_capability: Agent Memory
prerequisites: [AGENT-MEMORY-01, AGENT-MEMORY-03]
depends_on: [DEFINE_MEMORY_CANDIDATE_MODEL.md, PROMOTE_REJECT_AND_REVISE_MEMORY.md]
can_parallelize_with: []
---
State: Implemented. Delivered by PR #1240 (issue #1082, 2026-05-23).

# EXPLAIN_MEMORY_RECALL

## Purpose

Specify how recalled memory must explain why it was brought back, what its provenance is, and what
its review posture remains.

## What This Task Does

This task defines the implementation contract for recall explanation. It specifies:

- what a recall explanation must include,
- how recall links back to candidate or promoted memory provenance,
- and how recall remains inspectable in answers, orientation, resurfacing, or proposal support.

## Concretely

A later implementation should be able to produce a recall explanation that answers:

- what memory was recalled,
- why it was relevant now,
- what source or receipt supports it,
- whether it was inferred, reviewed, revised, or promoted,
- and what authority limits still apply.

## Why This Matters

The concept contract says recall that influences answers, orientation, or write proposals must be
explainable through receipts or equivalent review artifacts. If recall cannot explain itself, memory
becomes hidden state instead of inspectable support material.

## Acceptance Criteria

- [ ] Recalled memory is specified as including source provenance and review posture in its
  explanation surface. Verify: `tests/agent_memory/test_memory_recall_explanation.py::test_recall_explanation_includes_source_and_review_state`
- [ ] Recall explanation includes a "why this matters now" rationale rather than only replaying the
  stored memory text. Verify: `tests/agent_memory/test_memory_recall_explanation.py::test_recall_explanation_includes_why_now`
- [ ] Recall explanation preserves whether the memory was inferred, promoted, revised, or rejected
  historically. Verify: `tests/agent_memory/test_memory_recall_explanation.py::test_recall_explanation_preserves_memory_lifecycle_state`
- [ ] Recall explanation preserves authority limits instead of implying recalled memory is always
  actionable truth. Verify: `tests/agent_memory/test_memory_recall_explanation.py::test_recall_explanation_preserves_authority_limits`

## How to Verify (Pre-Merge)

- Add or update the recall-explanation tests named in the acceptance criteria.
- Confirm recall output can point back to receipts or source artifacts.
- Confirm explanation requirements work across answer, orientation, resurfacing, and proposal
  contexts without changing authority by themselves.

## Out of Scope

- Candidate-memory modeling.
- Review queue mechanics.
- Promotion decision logic.
- Final write-authority enforcement.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

- #1082 — [Impl] Agent Memory — Explainable Recall Surfaces
