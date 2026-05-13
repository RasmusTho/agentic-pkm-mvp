---
name: Emit Context Bundle from Retrieval
description: Specify how retrieval emits an inspectable context bundle rather than only ranked hits.
task_id: CONTEXT-BUNDLES-02
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md]
can_parallelize_with: []
---

# EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL

## Purpose

Specify how retrieval should emit a reviewable context bundle instead of leaving downstream surfaces
with only a ranked candidate list.

This task translates the contract boundary between "what matched" and "what was selected, why, and
with what authority" into a bounded implementation target.

## What This Task Does

This task defines the implementation contract for retrieval-side bundle emission. It specifies:

- when retrieval must emit a context bundle,
- how selected items differ from raw ranked results,
- how exclusions are represented when they affect interpretation,
- and how retrieval marks bundle authority for answer/propose/write separation.

## Concretely

A later implementation should be able to take retrieval results and emit:

- a selected subset of included items,
- explicit exclusions when scope or trust removes something important,
- rationale for why each included item was selected,
- and authority flags showing that retrieval output may answer without silently authorizing writes.

The output is a bundle or bundle reference, not just a hit list.

## Why This Matters

The contract says a context bundle is the auditable envelope around retrieval output. If retrieval
never emits that envelope, downstream orientation, resurfacing, and writeback flows either lose
explanation or reinvent bundle assembly in inconsistent ways.

## Acceptance Criteria

- [ ] Retrieval emission is specified as producing a context bundle or stable bundle reference in
  addition to ranked retrieval results. Verify: `tests/retrieval/test_context_bundle_emission.py::test_retrieval_emits_context_bundle`
- [ ] The emission contract distinguishes ranked candidates from selected included items used for
  human-facing output. Verify: `tests/retrieval/test_context_bundle_emission.py::test_retrieval_distinguishes_candidates_from_selected_context`
- [ ] Retrieval-side bundle emission preserves explicit exclusions when exclusion changes answer
  interpretation or authority. Verify: `tests/retrieval/test_context_bundle_emission.py::test_retrieval_context_bundle_records_interpretation_affecting_exclusions`
- [ ] Retrieval emission marks `may_write` as false unless a downstream governed action explicitly
  upgrades authority. Verify: `tests/retrieval/test_context_bundle_emission.py::test_retrieval_context_bundle_does_not_authorize_writeback`

## How to Verify (Pre-Merge)

- Add or update retrieval-layer tests named above.
- Confirm the output shape still exposes retrieval ranking diagnostics without collapsing them into
  selected context.
- Confirm retrieval emits bundle authority separately from downstream write-governance logic.

## Out of Scope

- Orientation-specific bundle assembly.
- Resurfacing-specific "why now" logic.
- Write proposal execution or receipt persistence.
- Memory promotion from retrieval outputs.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`
- `docs/CONTEXT_BUNDLES/DEFINE_CONTEXT_BUNDLE_SCHEMA.md`

## Related GitHub Issues

Filed as GitHub Issue [#896](https://github.com/RasmusTho/agentic-pkm-mvp/issues/896).
Parent feature issue: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894).
Depends on schema issue [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895).
