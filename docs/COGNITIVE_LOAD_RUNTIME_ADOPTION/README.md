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

State: Filed specification for open parent feature issue #1638. GitHub Issue #1638 remains the
authoritative backlog and validation surface.

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
non-authoritative posture informs this specification, but #1647 is not a child issue under #1638.

## Task List

1. [PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md](PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md) - existing
   issue [#1679](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1679), ready.
2. [SURFACE_SCARCE_RESURFACING_CARDS.md](SURFACE_SCARCE_RESURFACING_CARDS.md) - issue
   [#1680](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1680), ready.
3. [STAGE_TEXT_CORRECTION_PROPOSALS.md](STAGE_TEXT_CORRECTION_PROPOSALS.md) - issue
   [#1681](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1681), ready.
4. [PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md](PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md) - final closure and
   owner-doc promotion issue [#1682](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1682),
   blocked until the three runtime/UI children are delivered.

## Flat Execution Order

1. Deliver #1679.
2. Deliver scarce resurfacing cards and text correction proposals. These may run in parallel if
   separate worktrees avoid Companion UI conflicts.
3. Deliver owner-doc promotion and close #1638 only after child receipts are posted.

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

- #1679 - source-preserving summary fixtures.
- #1680 - scarce resurfacing cards.
- #1681 - text correction proposals.
- #1682 - owner-doc promotion and parent closure.
