---
name: Consume in Orientation and Resurfacing
description: Wire production orientation and resurfacing paths to consume emitted bundles.
task_id: CONTEXT-BUNDLES-RUNTIME-03
source_anchor: docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Runtime ownership map
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: [CONTEXT-BUNDLES-RUNTIME-02]
depends_on: [EMIT_FROM_REAL_RETRIEVAL.md]
can_parallelize_with: [CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md]
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563"
---

# CONSUME_IN_ORIENTATION_AND_RESURFACING

## Purpose

Make the production orientation and resurfacing paths consume emitted bundles, using the existing
bundle consumers and their authority gating, without upgrading authority.

## What This Task Does

Wires `app/orientation/bundle_consumer.py::build_orientation_frame_from_bundle` into the production
orientation path (`app/api/routes/orientation.py`) and
`app/resurfacing/bundle_consumer.py::build_resurfacing_bundle_frame` into the production resurfacing
path. Enforces the `intended_use` / authority gating already implemented in those consumers.

## Concretely

The production `/orientation` path (currently backed by `app.orientation.runtime`) and the resurfacing
path should consume a bundle, preserve provenance and exclusions, keep `may_write=false`, and reject
bundles not scoped for `orient` / `resurface`.

## Why This Matters

Orientation is where a human is most likely to trust a synthesized answer without re-reading sources.
If consumption is unwired, the production path cannot show what was included, excluded, or stale, and
resurfacing has no auditable "why now".

## Acceptance Criteria

- [ ] Production orientation consumes a bundle and preserves provenance + exclusions.
  Verify: `tests/api/test_orientation_consumes_bundle.py::test_orientation_path_consumes_bundle`
- [ ] Production orientation does not upgrade to write authority.
  Verify: `tests/api/test_orientation_consumes_bundle.py::test_orientation_path_non_write_authoritative`
- [ ] Production resurfacing consumes a bundle as suggestion-only with an auditable why-now.
  Verify: `tests/api/test_resurfacing_consumes_bundle.py::test_resurfacing_path_suggestion_only`
- [ ] Bundles not scoped for the surface are rejected.
  Verify: `tests/api/test_resurfacing_consumes_bundle.py::test_rejects_bundle_not_scoped_for_resurface`

## How to Verify (Pre-Merge)

- Add the route-layer tests named above.
- Run `ruff check app tests`.
- Confirm both surfaces remain read-only and reject mis-scoped bundles.

## Out of Scope

- Write linkage (#1564).
- Receipt projection (#1565).
- Knowledge Compilation reorientation packet.

## Related Docs

- `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md`
- `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_RESURFACING.md`
- `app/orientation/bundle_consumer.py`
- `app/resurfacing/bundle_consumer.py`
- `app/api/routes/orientation.py`

## Related GitHub Issues

- Implementation issue: [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563)
- Depends on: [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
