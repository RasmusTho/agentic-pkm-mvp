---
name: Use Context Bundle for Resurfacing
description: Specify how resurfacing uses context bundles to explain why-now suggestions.
task_id: CONTEXT-BUNDLES-04
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md]
can_parallelize_with: [USE_CONTEXT_BUNDLE_FOR_ORIENTATION]
---

# USE_CONTEXT_BUNDLE_FOR_RESURFACING

## Purpose

Specify how resurfacing uses a context bundle to support "why now" explanations without collapsing
semantic relatedness into urgency, authority, or write permission.

## What This Task Does

This task defines the implementation contract for resurfacing-side bundle consumption. It specifies:

- how resurfacing records the material it surfaced,
- how it records the signal or rationale for why now,
- and how it preserves the distinction between relevance and authority.

## Concretely

A later implementation should be able to emit a resurfacing result with:

- a bundle of selected supporting items,
- explicit "why now" rationale,
- provenance for the signals that triggered resurfacing,
- and clear authority posture showing that the bundle supports a suggestion, not a forced action.

## Why This Matters

Resurfacing is uniquely vulnerable to hidden ranking logic. The context bundle is what makes the
"why now" decision auditable instead of magical. Without it, quietly important suggestions become
hard to trust or dismiss.

## Acceptance Criteria

- [ ] Resurfacing consumption is specified as using a context bundle or stable bundle reference to
  support the surfacing event. Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_records_context_bundle`
- [ ] The resurfacing contract requires an explicit "why now" explanation tied to provenance, not
  only semantic relatedness. Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_includes_why_now_explanation`
- [ ] The resurfacing contract preserves the distinction between relatedness, priority, trust, and
  authority. Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_does_not_collapse_relatedness_into_priority_or_authority`
- [ ] Resurfacing bundle usage does not authorize direct writeback or promotion by itself. Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_remains_suggestion_only`

## How to Verify (Pre-Merge)

- Add or update the resurfacing tests named in the acceptance criteria.
- Confirm the resurfacing output can be dismissed or ignored without affecting authority state.
- Confirm "why now" is anchored to a recorded signal or relational change rather than opaque score
  ordering alone.

## Out of Scope

- Retrieval bundle emission.
- Orientation-frame assembly.
- Write proposal application.
- Memory promotion or review queues.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for resurfacing-side bundle usage.
