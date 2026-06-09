---
name: Cognitive Load Runtime Adoption Specification
description: Runtime/UI adoption specification for completing cognitive-load reduction epic #1638
type: specification
authority: Source specification for the remaining #1638 runtime adoption child issues
source_of_truth: docs/COGNITIVE_LOAD_PROJECTION_LAYER.md
related_docs:
  - docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md
  - docs/COMPANION_UI_PRODUCT_SPEC.md
  - companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
---

State: Delivered. Runtime/UI children #1679, #1680, and #1681 are delivered (PR #1689) and the final
owner-doc promotion and parent-closure issue #1682 is delivered. Parent feature issue #1638 is closed
after final validation. This directory is retained as the delivered specification of record.

# Cognitive Load Runtime Adoption Specification

This directory specifies the remaining runtime/UI adoption work needed before #1638 can close as a
validated cognitive-load capability. It does not reopen the already delivered research, owner-doc,
display-preference, listening, and proposal-review slices.

## Capability Boundary

Cognitive-load runtime adoption means making the existing Cognitive Load Projection Layer executable
on a few bounded Companion UI and Panel review surfaces while preserving source authority,
WriteGuard, receipts, provenance, and human confirmation.

The boundary is:

- source-preserving summary review fixtures;
- scarce, pointer-first resurfacing card rendering from the existing orientation payload;
- correction-as-proposal review for direct note-editor draft text;
- final validation and owner-doc promotion for #1638.

Source Understanding Mode remains a separate parent feature (#1646). Its source-primary and
non-authoritative posture informs this specification, but #1646/#1647 are **not** child issues or
blockers of #1638. They are a distinct Source Understanding parent path and were never a precondition
for closing this capability; #1638 closed on its own delivered child evidence (#1679/#1680/#1681) plus
this owner-doc promotion (#1682).

## Task List

1. [PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md](PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md) - existing
   issue [#1679](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1679), delivered.
2. [SURFACE_SCARCE_RESURFACING_CARDS.md](SURFACE_SCARCE_RESURFACING_CARDS.md) - issue
   [#1680](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1680), delivered.
3. [STAGE_TEXT_CORRECTION_PROPOSALS.md](STAGE_TEXT_CORRECTION_PROPOSALS.md) - issue
   [#1681](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1681), delivered.
4. [PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md](PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md) - final closure and
   owner-doc promotion issue [#1682](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1682),
   delivered after the three runtime/UI children; closed #1638.

## Flat Execution Order

1. Delivered: #1679.
2. Delivered: scarce resurfacing cards (#1680) and text correction proposals (#1681).
3. Delivered: owner-doc promotion (#1682); #1638 closed after final validation.

## Capability-Level Acceptance Criteria

- [ ] Source-preserving summary fixtures prove summaries/projections remain non-authoritative and
  cannot support governed confirmation without source identity.
  Verify: #1679 delivery receipt on #1638.
- [ ] Companion UI renders a scarce displayed subset of resurfacing candidates with `why_now`,
  source/provenance, signal labels, and no notification or urgency semantics.
  Verify: delivery receipt for `SURFACE_SCARCE_RESURFACING_CARDS.md` on #1638.
- [ ] Direct note-editor draft correction assistance is proposal-class only and cannot mutate the
  canonical note until explicit human save.
  Verify: delivery receipt for `STAGE_TEXT_CORRECTION_PROPOSALS.md` on #1638.
- [ ] Owner docs distinguish shipped cognitive-load runtime support from remaining target-state work
  and record #1646/#1647 as a separate Source Understanding path.
  Verify: delivery receipt for `PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md` and closed #1638.

## Verification Path

Task-level verification follows each task file's `How to Verify (Pre-Merge)` section. Parent-level
verification lives on GitHub Issue #1638 as child delivery receipts.

## Validation / Acceptance Path

GitHub Issue #1638 is the validation hub. Each child PR must post a short validation receipt to
#1638 before the next dependent child is picked up. Owner-doc promotion happens only in the final
child after runtime/UI evidence exists.

## Relationship to GitHub Issues

The live parent feature issue is [#1638](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638).
Child issues are execution artifacts. This specification is the source reference for their
acceptance criteria and verification approach.

- #1679 - source-preserving summary fixtures, delivered by PR #1689.
- #1680 - scarce resurfacing cards, delivered by PR #1689.
- #1681 - text correction proposals, delivered by PR #1689.
- #1682 - owner-doc promotion and parent closure, delivered; closed #1638.
- #1646/#1647 - Source Understanding Mode, a separate parent path; never a #1638 child or blocker.
