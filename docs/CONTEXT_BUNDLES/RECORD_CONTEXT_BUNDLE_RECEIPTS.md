---
name: Record Context Bundle Receipts
description: Specify how bundle creation and use leave inspectable receipts with provenance.
task_id: CONTEXT-BUNDLES-06
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to provenance and receipts
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02, CONTEXT-BUNDLES-05]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md, CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md]
can_parallelize_with: []
status: implemented
implementation: app/receipts/bundle_receipts.py
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/949"
---

# RECORD_CONTEXT_BUNDLE_RECEIPTS

## Purpose

Specify how context-bundle creation and downstream use leave inspectable receipts so the human can
see what context was selected, what was excluded, and how the bundle influenced answers,
orientation, resurfacing, or proposals.

## What This Task Does

This task defines the implementation contract for bundle-related receipts. It specifies:

- which bundle lifecycle events must leave receipts,
- what provenance and exclusion details must be retained,
- and how receipt linkage works across retrieval, orientation, resurfacing, and proposal flows.

## Concretely

A later implementation should be able to record receipts for events such as:

- bundle created from retrieval,
- bundle consumed by orientation,
- bundle used to justify resurfacing,
- bundle attached to a write proposal,
- and bundle marked stale or expired for later audit.

## Why This Matters

The concept contract says provenance explains why items were selected and receipts explain why the
bundle exists and how it was used. If receipts are missing, the bundle becomes another opaque
runtime object instead of a reviewable bridge artifact.

## Acceptance Criteria

- [x] The implementation spec requires receipts for bundle creation and for at least one downstream
  use path. Verify: `tests/receipts/test_context_bundle_receipts.py::test_context_bundle_receipt_records_sources`
- [x] Bundle receipts preserve included items, relevant exclusions, authority posture, and
  provenance strongly enough for later audit. Verify: `tests/receipts/test_context_bundle_receipts.py::test_context_bundle_receipt_preserves_exclusions_and_authority`
- [x] Bundle receipts distinguish creation, consumption, and stale-or-expired reuse events. Verify: `tests/receipts/test_context_bundle_receipts.py::test_context_bundle_receipts_distinguish_creation_consumption_and_expiry`
- [x] Receipt recording does not silently promote bundle contents into memory or knowledge. Verify: `tests/receipts/test_context_bundle_receipts.py::test_context_bundle_receipt_does_not_promote_to_memory`

## How to Verify (Pre-Merge)

- Add or update the receipt-focused tests named in the acceptance criteria.
- Confirm receipt fields map back to bundle identity and provenance instead of storing only opaque
  text.
- Confirm receipt rules cover both bundle creation and later use.

## Out of Scope

- Defining a full receipt storage backend.
- Deciding UI presentation of receipts.
- Memory review and promotion logic.
- General event-envelope changes outside bundle-related receipt needs.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONTEXT_BUNDLES/CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`

## Related GitHub Issues

- Implementation issue: [#949](https://github.com/RasmusTho/agentic-pkm-mvp/issues/949)
- Pull request: [#954](https://github.com/RasmusTho/agentic-pkm-mvp/pull/954)
- Parent feature: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894)
