---
name: Define Context Bundle Schema
description: Specify the minimal inspectable schema and authority flags for context bundles.
task_id: CONTEXT-BUNDLES-01
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Required fields
parent_capability: Context Bundles
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# DEFINE_CONTEXT_BUNDLE_SCHEMA

## Purpose

Define the minimal shape that makes a context bundle inspectable, auditable, and safe to pass
between retrieval, orientation, resurfacing, and write-proposal surfaces.

Without a schema task, downstream tasks will invent incompatible bundle shapes and lose the contract
distinction between selected context, provenance, and authority flags.

## What This Task Does

This task specifies the implementation contract for a minimal context-bundle schema. It defines:

- identity and creation metadata,
- trigger and intended-use fields,
- scope,
- included and excluded items,
- authority flags,
- stale or expiry posture,
- and receipt linkage.

It also states which fields are required for a bundle to be considered inspectable enough for human
review.

## Concretely

The resulting implementation spec should let a later PR add a structure that can express examples
such as:

- a retrieval bundle that may answer but may not write,
- an orientation bundle that carries recent deltas plus explicit exclusions,
- or a resurfacing bundle with a "why now" rationale and stale posture.

Expected implementation outputs include a schema artifact, serialization contract, or typed model
that can satisfy the fields named in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.

## Why This Matters

The contract already says a context bundle is not just a search result or prompt stuffing. A schema
task is what makes that enforceable in implementation. If the shape is loose, downstream surfaces
will quietly drop exclusions, provenance, or authority flags and the bundle stops being reviewable.

## Acceptance Criteria

- [ ] The implementation spec names the minimal required bundle fields: identity, creation time,
  trigger, intended use, scope, included items, excluded items, authority flags, expiry, and
  receipts. Verify: `tests/context_bundles/test_context_bundle_schema.py::test_minimal_context_bundle_schema`
- [ ] Included and excluded items preserve enough structure to record provenance, reason, and trust
  posture per item. Verify: `tests/context_bundles/test_context_bundle_schema.py::test_context_bundle_items_preserve_reason_and_provenance`
- [ ] Authority is modeled as distinct flags rather than one collapsed permission bit. Verify: `tests/context_bundles/test_context_bundle_schema.py::test_context_bundle_authority_flags_are_distinct`
- [ ] The schema spec explicitly preserves stale or expiry posture instead of treating bundles as
  permanently current. Verify: `tests/context_bundles/test_context_bundle_schema.py::test_context_bundle_schema_carries_expiry_posture`

## How to Verify (Pre-Merge)

- Add or update the schema-facing tests named in the acceptance criteria.
- Confirm the implementation surface can express both included and excluded items without dropping
  rationale or provenance.
- Confirm there is no single "authorized" field that collapses `may_answer`, `may_orient`,
  `may_resurface`, `may_propose`, and `may_write`.

## Out of Scope

- Emitting bundles from retrieval.
- Consuming bundles inside orientation or resurfacing.
- Linking bundles to write proposals or receipts.
- Deciding durable storage backends for bundle history.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONTEXT_BUNDLES/README.md`
- `docs/CONTEXT_BUNDLES/EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md`

## Related GitHub Issues

Filed as GitHub Issue [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895).
Parent feature issue: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894).
