---
name: Stage Text Correction Proposals
description: Add proposal-class correction review for direct note-editor draft text without silent save
task_id: CLRA-03
source_anchor: docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Text-production mode
parent_capability: cognitive-load-runtime-adoption
prerequisites: []
depends_on: []
can_parallelize_with: [PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md, SURFACE_SCARCE_RESURFACING_CARDS.md]
---

# Stage Text Correction Proposals

## Purpose

This task makes the text-production contract executable on the smallest shipped authoring surface:
the direct note editor. It gives the human reviewable correction proposals without dictation/STT,
silent autocorrect, or automatic canonical writes.

## What This Task Does

Add a UI-internal correction proposal model and a deterministic fixture-driven proposal surface for
draft text in the direct note editor. The first implementation may use fixture/static suggestions
only; it must not introduce an LLM, backend correction API, dictation engine, or persistence layer.

## Concretely

The direct note editor gains a correction review surface that can display `CorrectionProposal`
objects:

- `id`
- `tier`
- `original_text`
- `proposed_text`
- `range`
- `reason`
- `meaning_cue`
- `confidence` or `posture`

Each proposal shows the original and proposed token, tier, reason/meaning cue, and a clear "keep
mine" path. Accepting a proposal changes only the local textarea draft. The canonical note changes
only if the human then presses the existing Save control, which still posts to
`/api/companion/note/save`.

Where browser-local TTS/read-back is available, the correction proposal or resulting draft should be
readable through the existing read-back controls. Read-back must read the actual draft under review.

## Why This Matters

Severe spelling/encoding load is a real cognitive-load surface. Native spellcheck remains useful,
but it does not solve far-from-target spelling, real-word errors, or the selection problem. Silent
autocorrect would transfer authorship away from the human.

## Acceptance Criteria

- [ ] The direct note editor renders a correction proposal surface with proposal-class authority
  posture and no backend correction API.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_correction_proposal_surface_is_ui_internal`
- [ ] Each proposal displays original token, proposed token, tier, reason or meaning cue, and a
  "keep mine" path.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_correction_proposal_fields_are_visible`
- [ ] Applying a proposal updates only the local editor draft and does not call
  `/api/companion/note/save`.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_accepting_correction_updates_draft_without_save`
- [ ] Canonical save still happens only through the existing explicit Save control.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_canonical_save_remains_explicit_note_save`
- [ ] Real-word/context flags are flag-only and never auto-applied.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_real_word_flags_are_never_auto_applied`
- [ ] Read-back uses the actual draft/proposal text under review, not a silently cleaned version.
  Verify: `tests/companion_ui/test_text_correction_proposals.py::test_readback_targets_actual_draft_after_correction_review`

## How to Verify (Pre-Merge)

- `git diff --check`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_text_correction_proposals.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_direct_note_editor.py tests/companion_ui/test_tts_readback.py`
- `ruff check app tests`

## Out of Scope

- Implementing dictation/STT.
- Implementing an LLM correction service.
- Implementing a backend correction API.
- Replacing native spellcheck.
- Changing `/api/companion/note/save`.
- Routing non-governance text correction through Panel confirmation.
- Auto-applying corrections or style rewrites.

## Related Docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md`
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`
- `tests/companion_ui/test_direct_note_editor.py`
- `tests/companion_ui/test_tts_readback.py`

## Related GitHub Issues

Execution issue: [#1681](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1681).
Parent validation hub: [#1638](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638).
