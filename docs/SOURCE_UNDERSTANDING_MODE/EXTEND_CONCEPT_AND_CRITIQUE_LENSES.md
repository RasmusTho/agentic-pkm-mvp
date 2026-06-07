---
name: Extend Concept And Critique Lenses
description: Add Concept and Critique lenses after the P0 source-to-understanding packet is validated.
task_id: SUMODE-P1
state: blocked-post-p0
issue: 1685
source_anchor: GitHub Issue #1646 :: Analysis lenses
parent_capability: SOURCE_UNDERSTANDING_MODE
prerequisites: [SUMODE-P0]
depends_on: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md]
can_parallelize_with: []
---

# Extend Concept And Critique Lenses

## Purpose

Concept and Critique are the first post-P0 lenses. They help the human understand what terms and assumptions matter without letting the agent's critique replace source review.

## What This Task Does

Extend the validated P0 packet shape with:

- Concept view: key concepts, definitions or working descriptions, source anchors, ambiguity, and prerequisite understanding.
- Critique view: uncertainties, assumptions, weaknesses, limits, missing evidence, and what the human should check.

Both lenses remain source-bounded and non-authoritative.

## Concretely

- Concept entries point to source spans or report missing anchors.
- Concept entries distinguish source-defined terms from agent-provided clarification.
- Critique entries distinguish source limitations from agent inference.
- Critique entries avoid presenting skepticism as fact.
- Selection mode stays scoped to the selected passage.

## Why This Matters

Concept and Critique are where "help me understand" can turn into hidden interpretation authority. These lenses must make uncertainty and source basis more visible, not less.

## Acceptance Criteria

- [ ] Concept lens returns source-anchored concepts with source-defined versus agent-clarified posture. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_concept_lens_separates_source_defined_and_agent_clarified_terms`.
- [ ] Concept lens reports anchor limitations instead of fabricating term provenance. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_concept_lens_degrades_when_term_anchors_are_unavailable`.
- [ ] Critique lens separates source-stated limitations from agent-inferred concerns. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_critique_lens_separates_source_limits_from_agent_inference`.
- [ ] Critique lens identifies review-needed items without treating them as settled defects. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_critique_lens_marks_review_needed_without_overclaiming`.
- [ ] Selection-scoped Concept/Critique output does not claim full-document coverage. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_selection_concept_critique_lenses_stay_selection_scoped`.
- [ ] Adding the lenses does not mutate canonical artifacts, notes, or memory. Verify: `tests/source_understanding/test_concept_critique_lenses.py::test_concept_critique_lenses_are_read_only`.

## How to Verify (Pre-Merge)

Local:

- `pytest tests/source_understanding/test_concept_critique_lenses.py`
- re-run the P0 packet tests to prove backwards compatibility
- `git diff --check`
- `python3 scripts/docs_guard.py` if docs/contracts change

Post-merge:

- Post a child validation receipt to #1646 naming the packet fields added, fixture coverage, and how source-vs-agent interpretation is kept distinct.

## Out of Scope

- Integration and Action lenses.
- Stabilized-note apply behavior.
- Vault-wide concept graph building.
- Automatic concept-note creation.
- Treating critique output as source fact or as approval to act.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- Prerequisite: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md](DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md)
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Semantic transformations`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: WP-E`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md :: Source as role`

## Related GitHub Issues

GitHub Issue #1685. It must remain `agent:blocked` until #1647 validates the packet pattern and #1646 records the unblock decision.
