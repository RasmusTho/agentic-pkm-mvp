---
name: Prove Source-Preserving Summary Review
description: Add focused fixtures proving summaries remain non-authoritative and source-first
task_id: CLRA-01
source_anchor: docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test
parent_capability: cognitive-load-runtime-adoption
prerequisites: []
depends_on: []
can_parallelize_with: [SURFACE_SCARCE_RESURFACING_CARDS.md, STAGE_TEXT_CORRECTION_PROPOSALS.md]
---

# Prove Source-Preserving Summary Review

## Purpose

This task makes the FA-4 source-preserving summary boundary executable. It proves summaries and
projection audio remain entry points for review, not source authority or sufficient basis for
governed confirmation.

## What This Task Does

Add regression fixtures/tests across Companion UI or Panel proposal-review surfaces that distinguish
canonical source facts from agent interpretation and prevent summary-only review from becoming an
approval path.

## Concretely

Implement existing issue #1679. The expected output is a focused test/fixture set proving:

- source facts and agent interpretation are distinct;
- summary/projection text is marked non-authoritative;
- source-anchor limitations are visible;
- governed confirmation degrades or is unavailable when only summary context exists;
- TTS/read-back never presents summary audio as source audio.

## Why This Matters

Summaries reduce access cost, but LLM faithfulness remains a known risk. If a summary can stand in
for source review, cognitive-load support turns into authority loss.

## Acceptance Criteria

- [ ] Fixtures distinguish canonical source facts from agent interpretation/projection text.
  Verify: `tests/companion_ui/test_source_preserving_summary_review.py::test_source_fact_and_agent_interpretation_are_separate`
- [ ] Summary/projection text is marked non-authoritative in the rendered or modeled surface.
  Verify: `tests/companion_ui/test_source_preserving_summary_review.py::test_summary_projection_is_marked_non_authoritative`
- [ ] Source anchor limitations are visible when a summary cannot support claim-level source review.
  Verify: `tests/companion_ui/test_source_preserving_summary_review.py::test_source_anchor_limitations_are_visible`
- [ ] Governed confirmation cannot proceed from summary-only context.
  Verify: `tests/companion_ui/test_source_preserving_summary_review.py::test_summary_only_context_cannot_enable_governed_confirmation`
- [ ] Summary read-back is not presented as source audio.
  Verify: `tests/companion_ui/test_source_preserving_summary_review.py::test_summary_readback_is_not_source_audio`

## How to Verify (Pre-Merge)

- `git diff --check`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_source_preserving_summary_review.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_tts_readback.py`
- `ruff check app tests`

## Out of Scope

- Implementing summary generation.
- Implementing Source Understanding Mode.
- Changing Panel confirmation semantics.
- Changing durable receipt semantics.
- Implementing server-side TTS.

## Related Docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md`
- `docs/PANEL_AGENT.md`
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md`

## Related GitHub Issues

- Existing execution issue: [#1679](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1679).
- Related separate parent: [#1646](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1646).