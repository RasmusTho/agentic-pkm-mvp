---
name: Emit From Real Retrieval
description: Wire emit_retrieval_bundle into the real retrieval capability so production emits bundles.
task_id: CONTEXT-BUNDLES-RUNTIME-02
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: [CONTEXT-BUNDLES-RUNTIME-01]
depends_on: [EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md]
can_parallelize_with: []
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562"
---

# EMIT_FROM_REAL_RETRIEVAL

## Purpose

Make the real retrieval path emit an inspectable `ContextBundle` against the live vault/index, so the
construction route returns real bundles rather than synthetic ones.

## What This Task Does

Wires `app/retrieval/bundle_emission.py::emit_retrieval_bundle` into the real retrieval capability
(`app/retrieval/capability.py::RetrievalResponse`) and surfaces the result through the #1560 route.
The work routes through the capability, not the raw-cosine `/search` route, which uses direct
`psycopg` and is not the preferred ports path.

## Concretely

Given a real `RetrievalResponse`, production retrieval should produce a `ContextBundle` that keeps
ranked candidates distinct from selected included items and carries `may_write=false`.

## Why This Matters

`emit_retrieval_bundle` exists but is never called in production. Until the real retrieval path emits
bundles, the construction route, consumers, and receipts have no live source of truth to operate on.

## Acceptance Criteria

- [ ] Production retrieval path emits a `ContextBundle` from a real `RetrievalResponse`.
  Verify: `tests/retrieval/test_production_bundle_emission.py::test_real_retrieval_emits_bundle`
- [ ] Ranked candidates remain distinct from selected included items.
  Verify: `tests/retrieval/test_production_bundle_emission.py::test_candidates_distinct_from_selected`
- [ ] Emitted bundle carries `may_write=false`.
  Verify: `tests/retrieval/test_production_bundle_emission.py::test_emitted_bundle_not_write_authoritative`
- [ ] Real-vault emission produces a runtime creation receipt.
  Verify: `tests/retrieval/test_production_bundle_emission.py::test_emission_records_creation_receipt`

## How to Verify (Pre-Merge)

- Add the retrieval-layer tests named above.
- Run `ruff check app tests`.
- Smoke against a seeded local vault and confirm a bundle is returned via the #1560 route.

## Out of Scope

- Orientation/resurfacing consumption (#1563).
- Write linkage (#1564).
- Receipt query projection (#1565).
- Refactoring the `/search` raw-cosine route off direct DB.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONTEXT_BUNDLES/EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md`
- `app/retrieval/bundle_emission.py`
- `app/retrieval/capability.py`

## Related GitHub Issues

- Implementation issue: [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562)
- Depends on: [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
