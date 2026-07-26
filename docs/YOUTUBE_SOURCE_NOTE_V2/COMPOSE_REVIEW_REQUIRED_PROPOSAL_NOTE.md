---
name: Compose review-required proposal note
description: Replace fixed candidate rendering with a composable, authority-banded proposal renderer.
task_id: YSNV2-03
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-02]
depends_on: [FIX_CANDIDATE_TRUTH_SURFACES.md]
can_parallelize_with: []
---

# Compose Review-Required Proposal Note

## Purpose

Provide a stable rendering seam that can compose evidence-bearing output without allowing generated content to overwrite or masquerade as human content.

## What This Task Does

Replaces the fixed About/Summary/Takeaways shape with three authority bands: owner-authored content, a single explicit proposals wrapper, and deterministic evidence/lineage. It composes registered module outputs, omits absent optional sections, and rejects banned unsupported rhetoric before rendering.

## Concretely

The owner band is created empty and preserved byte-for-byte on later candidate/replay attempts. Generated sections appear only beneath `## Proposals (non-authoritative)`. Deterministic source-quality, coverage, and lineage sections remain distinct from proposals.

## Why This Matters

An open extraction registry cannot add value when the renderer is closed, and a richer note must make authority legible at a glance.

## Acceptance Criteria

- [ ] The renderer keeps owner-authored takeaways/open threads outside generated content and never rewrites them.
  Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_preserves_human_authored_band_on_rerun`.
- [ ] Generated content is contained by one review-required proposal wrapper; absent optional modules produce no empty headings.
  Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_wraps_proposals_and_omits_absent_modules`.
- [ ] Rendered generated prose fails closed on the declared banned-phrasing lint.
  Verify: `tests/knowledge_acquisition/test_note_renderer.py::test_renderer_rejects_banned_generated_phrasing`.
- [ ] Candidate terminality remains tied to successful note materialization, not successful in-memory assembly.
  Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_is_terminal_only_after_note_materialization`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_preserves_human_authored_band_on_rerun tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_wraps_proposals_and_omits_absent_modules tests/knowledge_acquisition/test_note_renderer.py::test_renderer_rejects_banned_generated_phrasing tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_is_terminal_only_after_note_materialization`

## Out of Scope

Claims, durable extractions, transcript files, module routing, and applying D6 to synthesis or claim output.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`
- `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:high`, `agent:blocked` pending YSNV2-02. SBS class: Product/Runtime. Recommended capability: Terra/high; template/rendering work with authority-sensitive regression tests.
