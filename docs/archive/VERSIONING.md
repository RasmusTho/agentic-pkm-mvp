State: Legacy (archived).
# VERSIONING

## SoT Schema Version
- Current: v4.3 (previous: v4.2)
- v4.3 highlights:
  - Obsidian integration & lifecycle mirroring (file-first flows)
  - Promotion/export/backfill chain (Reviewer → SetEvaluator → Projector → Vault)
  - Episodic memory standardized across agents

## Release Details
- Release date: 2025-10-25
- Tag: `sot-v4.3`
- Compat: backward compatible with v4.2 data (new columns are additive)

## Migrations
- Alembic heads are merged; run:
  - PYTHONPATH="$(pwd)" alembic upgrade head
- If multiple heads appear:
  - PYTHONPATH="$(pwd)" alembic heads
  - PYTHONPATH="$(pwd)" alembic merge -m "merge heads" <head1> <head2>
  - Then upgrade head.

## Semantics
- Continue adding columns/indexes instead of destructive changes.
- Promote schema bumps when lifecycle, promotion, or export contracts change.

## Contracts & Tests
- Contract tests verify inputs→events→state transitions.
- E2E tests require: normalized objects, chunk offsets, embeddings ≥ chunks, audit completeness, promotion/export sync.
