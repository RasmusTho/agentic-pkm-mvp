---
name: Deliver P0 Source Understanding Packet
description: Deliver the first source-anchored Orientation, Structure, Claims, and Evidence packet for one narrow source or selection input path.
task_id: SUMODE-P0
state: ready-existing-issue-1647
source_anchor: docs/SOURCE_UNDERSTANDING_MODE/PARENT_FEATURE_ISSUE.md :: Implementation Tasks
parent_capability: SOURCE_UNDERSTANDING_MODE
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Deliver P0 Source Understanding Packet

## Purpose

This task proves the source-to-understanding pattern with the smallest viable Source Understanding slice. It is the only ready pickup child for #1646 until the packet, source anchor, and non-authoritative posture are validated.

## What This Task Does

Deliver one narrow input path for `Understand this source` or `Understand selection`. The output is a source-anchored packet with P0 lenses only:

- Orientation
- Structure
- Claims
- Evidence

The packet must mark itself as a non-authoritative understanding projection and preserve source anchors or explain anchor limitations.

## Concretely

- A fixture source document or selected passage enters the chosen path.
- The runtime returns a packet that names the source/scope and contains P0 lens sections.
- Claims distinguish source content from agent interpretation.
- Evidence links back to claims rather than becoming a generic summary.
- Selection mode stays scoped to the selected passage unless full-document context was explicitly supplied.
- No canonical note, memory record, or durable knowledge artifact is created by packet generation.
- The packet identifies a possible stabilized-note proposal path without auto-promoting it.

## Why This Matters

Without a proven P0 packet, later Concept/Critique/Integration/Action lenses would only multiply untested interpretation risk. This task establishes the authority boundary and fixture shape the rest of #1646 depends on.

## Acceptance Criteria

- [ ] User can run Source Understanding P0 on the chosen source document or selected passage input path. Verify: `tests/source_understanding/test_p0_packet.py::test_runs_source_understanding_on_chosen_input_path`.
- [ ] Output includes Orientation, Structure, Claims, and Evidence. Verify: `tests/source_understanding/test_p0_packet.py::test_p0_packet_includes_required_lenses`.
- [ ] Output explicitly marks itself as a non-authoritative understanding projection. Verify: `tests/source_understanding/test_p0_packet.py::test_p0_packet_marks_non_authoritative_projection`.
- [ ] Output includes source anchors/references where available, or explicitly reports anchor limitations. Verify: `tests/source_understanding/test_p0_packet.py::test_p0_packet_preserves_source_anchors_or_limitations`.
- [ ] Claims distinguish source content from agent interpretation. Verify: `tests/source_understanding/test_p0_packet.py::test_claims_distinguish_source_content_from_agent_interpretation`.
- [ ] Evidence links evidence to claims rather than producing a generic summary. Verify: `tests/source_understanding/test_p0_packet.py::test_evidence_links_to_claims`.
- [ ] Selection mode does not overclaim whole-document understanding. Verify: `tests/source_understanding/test_p0_packet.py::test_selection_packet_scopes_output_to_selection`.
- [ ] Packet generation does not create canonical knowledge artifacts or hidden memory. Verify: `tests/source_understanding/test_p0_packet.py::test_packet_generation_does_not_write_durable_knowledge`.
- [ ] A possible stabilized-note proposal path is identified without auto-promotion. Verify: `tests/source_understanding/test_p0_packet.py::test_packet_names_stabilized_note_proposal_path_without_invoking_it`.

## How to Verify (Pre-Merge)

Local:

- `pytest tests/source_understanding/test_p0_packet.py`
- focused Companion UI/API tests if the chosen input path is exposed through Companion UI
- `git diff --check`
- `python3 scripts/docs_guard.py` if docs/contracts change

Post-merge:

- Post a child validation receipt to #1646 with the chosen input path, packet fixture, tests, and any packet-shape changes that affect blocked children.

## Out of Scope

- Concept, Critique, Integration, or Action lenses.
- A durable stabilized-note proposal workflow.
- Citation manager behavior.
- Generic PDF reader replacement.
- TTS/listening or display-preference work.
- Auto-promotion into canonical notes, concept notes, or memory.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- `docs/HUMAN-FLOWS.md :: Canonical human loops`
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md :: source authority`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Core Rules`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: WP-E`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`

## Related GitHub Issues

Mapped to existing GitHub Issue #1647. Parent validation hub: #1646.
