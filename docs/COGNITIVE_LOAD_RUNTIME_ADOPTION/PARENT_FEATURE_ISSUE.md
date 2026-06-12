State: Delivered and closed. GitHub Issue #1638 was the authoritative backlog and validation surface
for Cognitive Load Runtime Adoption. Runtime/UI children #1679, #1680, and #1681 are delivered
(PR #1689) and the final owner-doc promotion #1682 is delivered; #1638 is closed after final
validation. Source Understanding Mode (#1646/#1647) remains a separate, still-open parent path.

# Epic: Cognitive Load Runtime Adoption

Live GitHub parent issue:
[#1638](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638).

## Context

The Cognitive Load Projection Layer defines cognitive-load reduction as a central Yggdrasil
cognitive-prosthesis capability: reduce decoding, parsing, spelling, source-comparison, decision,
orientation, and resumption friction without reducing the human's reasoning task or transferring
authority to projections.

Most foundation and runtime/UI work for #1638 is delivered. The remaining parent work is to promote
owner docs and close the parent after final validation.

Source Understanding Mode (#1646/#1647) is related but separate. It reuses the same source-primary,
non-authoritative review posture, but it is not a child of #1638.

## Scope

- Treat #1638 as the live validation hub.
- Preserve the delivered child map for #1679, #1680, and #1681.
- Keep #1682 as the final child for owner-doc promotion and parent closure.

## Source Anchors

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Core Rules`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Resurfacing mode`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Text-production mode`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: Wave 2 Addendum`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: Wave 3 Addendum`
- `docs/COMPANION_UI_PRODUCT_SPEC.md :: Resurface`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md :: Success Payload`
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md :: artifact`
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md :: Endpoint`
- `https://github.com/RasmusTho/agentic-pkm-mvp/issues/1646`

## Constraints

- Do not make #1638 a direct pickup issue.
- Do not make #1647 a child of #1638.
- Do not introduce new public backend APIs for this breakdown.
- Do not mutate canonical Markdown from display, summary, resurfacing, listening, or correction
  projections except through the owning authorized save/apply/confirmation path.
- Do not treat resurfacing presence as priority, urgency, approval, memory promotion, or write
  authority.
- Do not treat correction suggestions as authorial truth; the human owns meaning and voice.

## Acceptance Criteria

- [ ] Source-preserving summary review is covered by focused fixtures/tests.
  Verify: #1679 delivery receipt on #1638.
- [ ] Scarce resurfacing-card rendering is delivered against existing orientation payload fields.
  Verify: delivery receipt for `SURFACE_SCARCE_RESURFACING_CARDS.md` on #1638.
- [ ] Correction-as-proposal draft review is delivered for direct note-editor text without silent
  canonical mutation.
  Verify: delivery receipt for `STAGE_TEXT_CORRECTION_PROPOSALS.md` on #1638.
- [ ] Owner docs are promoted only after child evidence exists and #1646/#1647 are recorded as a
  separate Source Understanding parent path.
  Verify: delivery receipt for `PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md` and closed #1638.

## Implementation Tasks

1. `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md` - delivered by
   issue #1679 / PR #1689.
2. `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/SURFACE_SCARCE_RESURFACING_CARDS.md` - filed as #1680
   and delivered by PR #1689.
3. `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/STAGE_TEXT_CORRECTION_PROPOSALS.md` - filed as #1681
   and delivered by PR #1689.
4. `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/PROMOTE_COGNITIVE_LOAD_OWNER_DOCS.md` - filed as #1682
   (remaining final child).

## Verification Path

Each child issue must name concrete tests or doc receipts in its own acceptance criteria. Parent
verification is the set of child delivery receipts posted to #1638 plus the final owner-doc
promotion receipt.

## Validation / Acceptance Path

Keep validation evidence on #1638. Close #1638 only after all child issues are delivered or
explicitly superseded with a receipt, and after owner docs truthfully distinguish shipped support
from remaining target-state work.

## Out of Scope

- Implementing Source Understanding Mode.
- Implementing full summary generation.
- Implementing dictation/STT.
- Implementing server-side TTS.
- Implementing notification infrastructure or learning/spaced-retrieval resurfacing.

## Suggested Validation

- `git diff --check`
- `python3 scripts/docs_guard.py`
- Child-specific focused tests named by the child issues.

## Source Docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md`
