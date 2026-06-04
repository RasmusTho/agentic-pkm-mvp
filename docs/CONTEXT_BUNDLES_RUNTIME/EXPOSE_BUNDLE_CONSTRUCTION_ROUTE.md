---
name: Expose Bundle Construction Route
description: Read-only production route that returns an inspectable ContextBundle envelope.
task_id: CONTEXT-BUNDLES-RUNTIME-01
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Required fields
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: []
depends_on: []
can_parallelize_with: []
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560"
---

# EXPOSE_BUNDLE_CONSTRUCTION_ROUTE

## Purpose

Expose the first production surface for Context Bundles: a read-only route that returns an
inspectable `ContextBundle` envelope, establishing the route contract before real-vault emission
lands.

## What This Task Does

Adds a read-only HTTP route and response contract returning the `ContextBundle` envelope (authority
flags, included/excluded items, expiry posture), registered through the existing seam pattern in
`app/api/app.py`. The bundle is sourced from existing typed-contract building blocks; there is no
real-retrieval dependency and no vault mutation in this slice.

## Concretely

A caller should be able to `GET` a bundle route (e.g. `/api/context-bundles/{id}` or
`/api/companion/context-bundle`) and receive the self-describing bundle envelope, including authority
flags surfaced verbatim, with `may_write` never defaulted to true.

## Why This Matters

The typed-contract layer is shipped but unreachable from production. Without a route contract, every
downstream slice (emission, consumption, linkage, receipts) has nowhere to surface a bundle and the
capability stays invisible to the runtime.

## Acceptance Criteria

- [ ] Route returns a `ContextBundle` envelope including authority flags and exclusions.
  Verify: `tests/api/test_context_bundle_route.py::test_route_returns_inspectable_bundle_envelope`
- [ ] Route is read-only and performs no vault mutation.
  Verify: `tests/api/test_context_bundle_route.py::test_bundle_route_is_read_only`
- [ ] `may_write` is surfaced as-is and never defaulted true.
  Verify: `tests/api/test_context_bundle_route.py::test_route_does_not_upgrade_authority`
- [ ] Route is registered through the seam without import-time failure.
  Verify: `tests/api/test_context_bundle_route.py::test_route_registered_via_seam`

## How to Verify (Pre-Merge)

- Add the route-layer tests named above.
- Run `ruff check app tests`.
- Confirm the response model exposes authority flags and exclusions and performs no write.

## Out of Scope

- Real retrieval emission (#1562).
- Orientation/resurfacing consumption (#1563).
- Write linkage (#1564).
- Receipt persistence/projection (#1565).
- UI rendering.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONTEXT_BUNDLES_RUNTIME/README.md`
- `app/context_bundles/schema.py`
- `app/api/app.py`

## Related GitHub Issues

- Implementation issue: [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
