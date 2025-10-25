# Testing Strategy — SoT v4.2

## Philosophy
- Every agent has a deterministic, self-contained test suite.
- End-to-end tests simulate ingestion on a small synthetic corpus.
- All tests run against a temporary Postgres database (local container).
- No LLM calls in unit tests — Plan/Reflect is mocked.

## Layers
### 1. Unit tests
- Located in `tests/agents/`
- Validate internal logic and SQL writes
- Use local test data via pytest tmp_path

### 2. Integration tests
- Cover agent → database roundtrips
- Validate `trace_id` propagation and audit writes
- Run in-memory embeddings / BM25 for speed

### 3. E2E tests
- Located in `tests/e2e/`
- Exercises Normalizer → Projector
- Verifies object counts, audit, chunks, embeddings

## Running
PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q

## Guidelines
- Keep fixtures explicit; no autouse.
- No sleeps, randomness, or remote I/O.
- One failing test must identify one defect.
- Each agent must reach ≥90% coverage on logic branches.
