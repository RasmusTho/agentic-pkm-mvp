---
name: Expose Receipt Projection
description: Read-only projection exposing bundle provenance and exclusions through receipts/query.
task_id: CONTEXT-BUNDLES-RUNTIME-05
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to provenance and receipts
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: [CONTEXT-BUNDLES-RUNTIME-03, CONTEXT-BUNDLES-RUNTIME-04]
depends_on: [CONSUME_IN_ORIENTATION_AND_RESURFACING.md, CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md]
can_parallelize_with: []
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565"
---

# EXPOSE_RECEIPT_PROJECTION

## Purpose

Expose bundle provenance and exclusions through a read-only receipt/query projection so bundle
creation, consumption, and stale/expired reuse are auditable.

## What This Task Does

Adds a read-only projection/query surface over the bundle receipts produced by
`app/receipts/bundle_receipts.py` (`record_creation_receipt`, `record_consumption_receipt`,
`record_stale_receipt`), preserving provenance, exclusions, and authority posture. If a durable
receipt store or a new event family is required, `docs/EVENTS.md` and event-envelope tests must be
updated in this same slice.

## Concretely

A caller should be able to query bundle receipts and see, for a given bundle, its creation and at
least one downstream-use event, with included items, exclusions, and authority posture intact — and
nothing promoted into memory or knowledge.

## Why This Matters

`record_*_receipt()` returns objects but there is no persistence/query/projection surface today.
Without it, the bundle becomes another opaque runtime object instead of a reviewable bridge artifact.

## Acceptance Criteria

- [ ] Projection exposes creation + at least one downstream-use receipt with provenance.
  Verify: `tests/receipts/test_bundle_receipt_projection.py::test_projection_exposes_creation_and_consumption`
- [ ] Projection preserves exclusions and authority posture.
  Verify: `tests/receipts/test_bundle_receipt_projection.py::test_projection_preserves_exclusions_and_authority`
- [ ] Projection does not promote bundle contents to memory/knowledge.
  Verify: `tests/receipts/test_bundle_receipt_projection.py::test_projection_does_not_promote_to_memory`
- [ ] If a new event family is added, it is documented in `docs/EVENTS.md` with envelope tests;
  otherwise this slice introduces no new event family.
  Verify: writeback to `docs/EVENTS.md` + `tests/events/test_event_envelope.py` (in-slice), or an
  explicit "no new event family" note in the PR.

## How to Verify (Pre-Merge)

- Add the receipt-projection tests named above.
- Run `ruff check app tests`.
- Confirm receipt fields map back to bundle identity and provenance, not opaque text, and that no
  new event family is introduced without `docs/EVENTS.md` + envelope tests.

## Out of Scope

- Owner-doc promotion (#1566).
- UI rendering of receipts.
- Durable knowledge store.

## Related Docs

- `docs/CONTEXT_BUNDLES/RECORD_CONTEXT_BUNDLE_RECEIPTS.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/EVENTS.md`
- `app/receipts/bundle_receipts.py`

## Related GitHub Issues

- Implementation issue: [#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565)
- Depends on: [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563),
  [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
