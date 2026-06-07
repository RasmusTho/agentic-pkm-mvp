---
name: Connect Stabilized Note Proposal Handoff
description: Turn the validated P0 understanding packet into a reviewable stabilized-note proposal path without auto-promotion.
task_id: SUMODE-HANDOFF
state: blocked-post-p0
issue: 1684
source_anchor: docs/SOURCE_UNDERSTANDING_MODE/PARENT_FEATURE_ISSUE.md :: Implementation Tasks
parent_capability: SOURCE_UNDERSTANDING_MODE
prerequisites: [SUMODE-P0]
depends_on: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md]
can_parallelize_with: []
---

# Connect Stabilized Note Proposal Handoff

## Purpose

The P0 packet may identify a possible stabilized-note path, but #1646 is not done until the path is reviewable without turning interpretation into durable knowledge automatically. This task connects the packet to a proposal-class handoff.

## What This Task Does

Add the smallest governed handoff from a validated Source Understanding packet to a stabilized literature/concept note proposal. The handoff may reuse an existing proposal/staging seam or define a narrow new internal model, but it must not apply the proposal by itself.

## Concretely

- A P0 packet can produce a reviewable stabilized-note proposal object or staged review surface.
- The proposal names source identity, source anchors, packet scope, agent interpretation, and anchor limitations.
- The human can choose promote/apply through an existing governed path, or defer/reject/revise without mutating canonical artifacts.
- Defer/reject/revise remain local or proposal-state only unless a governed persistence contract already exists.
- Applying the proposal, if implemented in this slice, routes through WriteGuard/governance and receipt production.

## Why This Matters

Source understanding becomes dangerous when a helpful interpretation silently turns into canonical knowledge. The handoff must preserve the review object and make the promotion boundary explicit.

## Acceptance Criteria

- [ ] A validated P0 packet can stage or construct one reviewable stabilized-note proposal. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_p0_packet_can_stage_reviewable_stabilized_note_proposal`.
- [ ] The proposal carries source identity, packet scope, source anchors or limitations, and non-authoritative provenance. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_stabilized_note_proposal_preserves_source_and_packet_provenance`.
- [ ] Promote/apply is distinct from defer, reject, and revise. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_handoff_exposes_distinct_review_choices`.
- [ ] Defer/reject/revise do not mutate canonical source artifacts, generated notes, or memory. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_non_apply_choices_do_not_mutate_durable_surfaces`.
- [ ] If apply is implemented, it routes through the existing governed mutation path and receipt posture. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_apply_uses_governed_mutation_path_when_available`.
- [ ] If apply is not implemented, the surface honestly reports the apply path as unavailable rather than pretending promotion happened. Verify: `tests/source_understanding/test_stabilized_note_handoff.py::test_unavailable_apply_path_degrades_without_promotion`.

## How to Verify (Pre-Merge)

Local:

- `pytest tests/source_understanding/test_stabilized_note_handoff.py`
- focused Companion UI/API tests if the handoff is surfaced in UI
- `git diff --check`
- `python3 scripts/docs_guard.py` if docs/contracts change

Post-merge:

- Post a child validation receipt to #1646 naming the proposal shape, available review choices, mutation path posture, and receipt evidence or degraded apply posture.

## Out of Scope

- Implementing Concept/Critique/Integration/Action lenses.
- Full literature-note automation.
- Automatic concept-note creation.
- Hidden memory promotion.
- New public backend API unless #1647 validation shows the existing seams cannot support the handoff and owner docs are updated.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- Prerequisite: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md](DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md)
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md :: Proposal lifecycle`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Core Rules`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: WP-E`

## Related GitHub Issues

GitHub Issue #1684. It must remain `agent:blocked` until #1647 posts a P0 validation receipt to #1646.
