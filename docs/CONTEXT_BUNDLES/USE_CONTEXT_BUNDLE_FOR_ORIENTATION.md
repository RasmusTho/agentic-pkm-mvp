---
name: Use Context Bundle for Orientation
description: How orientation consumes context bundles to rebuild situational context.
task_id: CONTEXT-BUNDLES-03
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md]
can_parallelize_with: [USE_CONTEXT_BUNDLE_FOR_RESURFACING]
status: implemented
implementation: app/orientation/bundle_consumer.py
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/946"
---

# USE_CONTEXT_BUNDLE_FOR_ORIENTATION

## Purpose

Specify how orientation uses a context bundle to reconstruct situational state after interruption
without collapsing facts, inferred state, candidate next actions, and stale context into one
undifferentiated response.

## What This Slice Implements

`app/orientation/bundle_consumer.py` provides `build_orientation_frame_from_bundle`, which:

- requires `may_orient=True` on the bundle's authority flags and rejects `may_write=True`
- requires `"orient"` in `bundle.intended_use` — authority flag alone is not sufficient
- classifies each included item into `facts`, `inferences`, or `candidate_actions` based on
  `source_role`, `reason` text, and `provenance.origin`
- preserves per-item provenance and exclusions on the returned `OrientationBundleFrame`
- checks bundle expiry and surfaces `stale=True` when `stale_after` has passed, normalizing
  naive datetimes to UTC to prevent `TypeError` on comparison
- normalizes a caller-provided naive `now` to UTC by the same convention
- returns `read_only=True, may_write=False` — orientation never upgrades bundle authority

## Why This Matters

Orientation is where the human is most likely to trust a synthesized answer without re-reading every
source. If bundle consumption is underspecified here, orientation can quietly present inferences as
facts or stale signals as current state.

## Acceptance Criteria

- [x] Orientation consumption reads from a context bundle, not from opaque prompt state alone.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_uses_context_bundle`
- [x] The frame distinguishes facts, inferred state, candidate next actions, and stale context.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_labels_fact_inference_candidate_and_stale_context`
- [x] Orientation preserves source and exclusion provenance for human inspection.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_exposes_bundle_provenance_and_exclusions`
- [x] Orientation does not silently upgrade bundle authority into write authorization.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_bundle_remains_non_write_authoritative`
- [x] Bundles not scoped for orientation (`"orient"` absent from `intended_use`) are rejected.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_rejects_bundle_not_scoped_for_orient`
- [x] Naive `stale_after` and naive caller-provided `now` are normalized to UTC without raising `TypeError`.
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_stale_check_handles_naive_expiry_timestamp`
  Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_normalizes_naive_caller_now`

## Out of Scope

- Retrieval bundle emission.
- Resurfacing-specific surfacing decisions.
- Durable memory promotion from orientation outputs.
- Write proposal execution.
- API route wiring (production route integration is a follow-up slice).

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

- Implementation issue: [#946](https://github.com/RasmusTho/agentic-pkm-mvp/issues/946)
- Pull request: [#950](https://github.com/RasmusTho/agentic-pkm-mvp/pull/950)
- Parent feature: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894)
