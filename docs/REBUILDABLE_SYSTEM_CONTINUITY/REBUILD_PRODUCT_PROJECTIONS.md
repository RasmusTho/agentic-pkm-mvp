---
name: Rebuild Product Projections
description: Reconstruct object, vector, relation, and queue projections from declared retained sources with replay safety.
task_id: RSC-03
github_issue: 5284
source_anchor: "docs/EVENTS.md :: Outbox consumer contract"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-02]
depends_on: [PROVE_PRODUCT_TOTAL_LOSS.md]
can_parallelize_with: []
---

# Rebuild Product Projections

## Purpose

Complete the Product projection path so total loss covers the real object/vector/relation and
queued-work composition rather than one store in isolation.

## What This Task Does

Use owner-native store and event contracts to rebuild objects, embeddings/vector entries, relation
projections, and reconstructable pending work. Each record binds its replay tuple; replay is
idempotent; diagnostic JSONL is never treated as a canonical worker queue.

## Concretely

An isolated fixture erases all projection tables, replays retained sources/events twice, and proves
stable canonical outcomes, duplicate safety, and loud orphan/provenance refusal.

## Why This Matters

Cross-store drift and queue ambiguity can make individually rebuildable components compose into a
non-rebuildable system.

## Acceptance Criteria

- [ ] Object, vector, and relation projections converge from declared retained sources with exact
  source/generation/recipe provenance.
  - Verify: `tests/integration/test_projection_rebuild.py::test_object_vector_and_relation_projections_converge_from_retained_sources`
- [ ] Replaying the complete source set twice is idempotent and preserves canonical identities.
  - Verify: `tests/integration/test_projection_rebuild.py::test_projection_replay_is_idempotent`
- [ ] Reconstructable queued work comes only from the owning durable event/source contract; audit
  JSONL and absence of a row never authorize effect execution.
  - Verify: `tests/integration/test_projection_rebuild.py::test_queue_rebuild_rejects_diagnostic_and_unknown_effect_sources`

## How To Verify Pre-Merge

- `pytest -q tests/integration/test_projection_rebuild.py`
- Run targeted store, relation, event, and outbox tests selected from the diff.

## Out Of Scope

- Replaying unknown external effects, changing vault append transactions, or activating dormant MVR.

## Related Docs

- `docs/EVENTS.md`
- `docs/DB_SCHEMA.md`
- `docs/contracts/STORE_PORT.md`

## Related GitHub Issues

Coordinate but do not absorb #5162, #4659, and #3553.
