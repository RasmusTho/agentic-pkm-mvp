---
name: Use Context Bundle for Orientation
description: Specify how orientation consumes context bundles to rebuild situational context.
task_id: CONTEXT-BUNDLES-03
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md]
can_parallelize_with: [USE_CONTEXT_BUNDLE_FOR_RESURFACING]
---

# USE_CONTEXT_BUNDLE_FOR_ORIENTATION

## Purpose

Specify how orientation uses a context bundle to reconstruct situational state after interruption
without collapsing facts, inferred state, candidate next actions, and stale context into one
undifferentiated response.

## What This Task Does

This task defines the implementation contract for orientation-side bundle consumption. It specifies:

- how orientation assembles or consumes a bundle,
- how it distinguishes facts, inferred state, candidate actions, and stale context,
- and how it preserves bundle provenance for human review.

## Concretely

A later implementation should be able to produce an orientation frame backed by a bundle that
records:

- selected artifacts and signals used for the frame,
- exclusions that affected the frame,
- explicit labels for fact vs inference vs candidate action,
- and stale or expiry posture when the orientation snapshot may no longer be current.

## Why This Matters

Orientation is where the human is most likely to trust a synthesized answer without re-reading every
source. If bundle consumption is underspecified here, orientation can quietly present inferences as
facts or stale signals as current state.

## Acceptance Criteria

- [ ] Orientation consumption is specified as reading from a context bundle or bundle reference,
  not from opaque prompt state alone. Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_uses_context_bundle`
- [ ] The orientation contract distinguishes facts, inferred state, candidate next actions, and
  stale context in the assembled output. Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_labels_fact_inference_candidate_and_stale_context`
- [ ] Orientation preserves source and exclusion provenance strongly enough for a human to inspect
  why the frame was assembled. Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_exposes_bundle_provenance_and_exclusions`
- [ ] Orientation does not silently upgrade bundle authority into write authorization. Verify: `tests/orientation/test_context_bundle_orientation.py::test_orientation_bundle_remains_non_write_authoritative`

## How to Verify (Pre-Merge)

- Add or update the orientation tests named in the acceptance criteria.
- Confirm the orientation surface can explain what it used and what it left out.
- Confirm any orientation "next step" remains a candidate or proposal unless a separate governed
  action surface takes over.

## Out of Scope

- Retrieval bundle emission.
- Resurfacing-specific surfacing decisions.
- Durable memory promotion from orientation outputs.
- Write proposal execution.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for orientation-side bundle usage.
