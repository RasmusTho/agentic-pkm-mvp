# TESTING

## Layers
- Unit: pure functions and single-agent logic
- Contract: `.done` event payload shape and DB side-effects per agent
- E2E: normalizer → classifier → chunker → deduper → citation → indexer → reviewer → projector

## Commands
- Single test
  - pytest -q tests/agents/test_normalizer.py
- E2E graph
  - PYTHONPATH="$(pwd)" env DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q tests/e2e/test_pipe_graph.py

## Determinism
- Hashing-based embeddings in tests for stable semantics
- Fixed chunk sizes and overlap

## DB
- Local Postgres with pgvector
- Alembic upgrade before tests
