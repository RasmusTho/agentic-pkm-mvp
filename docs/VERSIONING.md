# VERSIONING

## SoT Schema Version
- Current: v4.2 (previous: v4.1)
- v4.2 aligns on:
  - LangGraph PER wrapper for agents (plan/act/reflect nodes)
  - Explicit event choreography with ingest.* and curation.*
  - Unified AMG/SetDB schema covering objects, chunks, embeddings, relations, sets, membership, decisions, audit

## Migrations
- Alembic heads are merged; run:
  - PYTHONPATH="$(pwd)" alembic upgrade head
- If multiple heads appear:
  - PYTHONPATH="$(pwd)" alembic heads
  - PYTHONPATH="$(pwd)" alembic merge -m "merge heads" <head1> <head2>
  - Then upgrade head.

## Semantics
- Backward compatible object payloads where possible.
- Column/index additions are preferred to destructive changes.
- Bump SOT_VERSION when schema affects data or agent contracts.

## Contracts & Tests
- Contract tests verify inputs→events→state transitions.
- E2E tests require: normalized objects, chunk offsets, embeddings ≥ chunks, audit completeness, projector sync.
