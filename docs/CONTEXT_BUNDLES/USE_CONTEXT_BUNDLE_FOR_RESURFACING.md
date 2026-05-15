---
name: Use Context Bundle for Resurfacing
description: How resurfacing uses context bundles to explain why-now suggestions.
task_id: CONTEXT-BUNDLES-04
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md]
can_parallelize_with: [USE_CONTEXT_BUNDLE_FOR_ORIENTATION]
status: implemented
implementation: app/resurfacing/bundle_consumer.py
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/947"
---

# USE_CONTEXT_BUNDLE_FOR_RESURFACING

## Purpose

Specify how resurfacing uses a context bundle to support "why now" explanations without collapsing
semantic relatedness into urgency, authority, or write permission.

## What This Slice Implements

`app/resurfacing/bundle_consumer.py` provides `build_resurfacing_bundle_frame`, which:

- requires a `WhyNowSignal(rationale, signal_name)` — both fields are required and non-blank;
  plain strings or empty/whitespace-only values are rejected so the surfacing decision is
  always anchored to a named, recorded signal
- requires `may_resurface=True` on the bundle's authority flags and rejects `may_write=True`
- requires `"resurface"` in `bundle.intended_use` — authority flag alone is not sufficient
- classifies included items into `priority_signals` (when the structured `source_role` field
  marks them as priority) or `relatedness_signals` otherwise; free-text reason substrings are
  not consulted because negated phrases like "not urgent" would otherwise be misclassified
- preserves bundle `excluded` items on `ResurfacingBundleFrame.exclusions` for human inspection
- checks bundle expiry and surfaces `stale=True` when `stale_after` has passed, normalizing
  naive datetimes to UTC to prevent `TypeError` on comparison
- normalizes a caller-provided naive `now` to UTC by the same convention
- returns `suggestion_only=True, may_write=False` — resurfacing never upgrades bundle authority

## Why This Matters

Resurfacing is uniquely vulnerable to hidden ranking logic. The context bundle is what makes the
"why now" decision auditable instead of magical. Without it, quietly important suggestions become
hard to trust or dismiss.

## Acceptance Criteria

- [x] Resurfacing reads from a context bundle to support the surfacing event.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_records_context_bundle`
- [x] The "why now" explanation is anchored to a `WhyNowSignal` with a required `signal_name` — not an opaque score.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_includes_why_now_explanation`
- [x] Relatedness, priority, trust, and authority remain distinct on the returned frame.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_does_not_collapse_relatedness_into_priority_or_authority`
- [x] Resurfacing bundle usage does not authorize direct writeback or promotion.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_remains_suggestion_only`
- [x] Bundles not scoped for resurfacing (`"resurface"` absent from `intended_use`) are rejected.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_rejects_bundle_not_scoped_for_resurface`
- [x] Naive `stale_after` and naive caller-provided `now` are normalized to UTC without raising `TypeError`.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_bundle_surfaces_stale_expiry_state`
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_normalizes_naive_caller_now`
- [x] Bundle exclusions are preserved on the frame for human inspection.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_frame_preserves_exclusions`
- [x] `WhyNowSignal` rejects blank or whitespace-only rationale/signal_name at construction.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_rejects_blank_why_now_signal_fields`
- [x] Priority classification relies on structured `source_role` only; free-text reason substrings are not consulted.
  Verify: `tests/resurfacing/test_context_bundle_resurfacing.py::test_resurfacing_priority_classification_uses_source_role_not_reason_text`

## Out of Scope

- Retrieval bundle emission.
- Orientation-frame assembly.
- Write proposal application.
- Memory promotion or review queues.
- API route wiring (production route integration is a follow-up slice).

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

- Implementation issue: [#947](https://github.com/RasmusTho/agentic-pkm-mvp/issues/947)
- Pull request: [#951](https://github.com/RasmusTho/agentic-pkm-mvp/pull/951)
- Parent feature: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894)
