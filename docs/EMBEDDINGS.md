State: Active (current).
# Embeddings

This document is the **normative specification** for how embeddings are produced, validated, recorded, and stored in the system.

Embeddings are **derived artifacts** (rebuildable). The canonical source of truth remains the vault-backed Markdown + ObjectStore payloads.

## Goals

- One consistent embedding pipeline across runtime (API/worker) that honors configuration:
  - `LLM_PROVIDER`
  - `OLLAMA_HOST`
  - `EMBED_MODEL`
  - `EMBED_DIM`
  - `EMBED_NORMALIZE` (if present; defaults to normalized vectors)
- A stable **embedding identity** that is recorded alongside vectors so we can detect drift.
- Clear operational behavior for dimension mismatch, model swaps, and rebuilds.

## High-level flow

1. Content is prepared for indexing (e.g., markdown semantic view).
2. Indexer resolves the **embedding identity** up-front.
3. Indexer calls the provider-aware embedding helper (`llm_embed_text`) with:
   - provider / base URL (via env + provider logic)
   - model name
   - expected dimension (guardrail)
   - normalize flag
4. The returned vector is validated (dimension + optional normalization expectations).
5. Vectors are **upserted** into `VectorIndex`.
6. Indexer emits index events to outbox (success/failure) with provenance.

## Configuration

### Required / primary env vars

- `LLM_PROVIDER`
  - Supported: `ollama`, `mock`
- `OLLAMA_HOST`
  - Example: `http://host.docker.internal:11434`
- `EMBED_MODEL`
  - Example: `nomic-embed-text:latest`
- `EMBED_DIM`
  - Example: `768`
  - Used as a **guardrail**. If provider returns a different dim, indexing fails for that object and an error event is emitted.

### Optional env vars

- `EMBED_NORMALIZE`
  - If set/used by the embedding helper; default behavior is to return **normalized** vectors.
  - Changing normalization changes the embedding identity and requires rebuilding the vector index.

## Embedding identity

The system maintains a stable identity string/record for embeddings. It is resolved by `get_embedding_identity()` and should include (at minimum):

- provider (e.g., `ollama`)
- model (e.g., `nomic-embed-text:latest`)
- expected dimension (e.g., `768`)
- normalize flag (e.g., `true`)

This identity must be:
- resolved **before** embedding,
- recorded with the vector index metadata / provenance,
- attached to emitted indexing events.

### Why identity matters

If you change:
- provider
- model
- dimension
- normalization

…then previously stored vectors are not comparable. The correct operation is to **rebuild** the vector index under the new identity.

## Call graph (runtime)

Normative call path:

- Indexer (worker/runtime) imports `llm_embed_text` from `app.index.embeddings`
- `app.index.embeddings.llm_embed_text(...)` routes to the provider-aware embedding implementation in `app.llm.embeddings.embed_text(...)`
- Provider logic uses `LLM_PROVIDER` and `OLLAMA_HOST` to decide how to call the backend.

Indexer must **not** call deterministic/test-only helpers in production paths.

## Indexing behavior and invariants

### Expected behavior

- For each object:
  - produce one or more vectors (depending on chunking/view)
  - upsert vectors into VectorIndex
  - emit `index.object.embedded` with:
    - object id
    - counts (vectors)
    - provenance (provider/model/identity)
    - view (e.g., `markdown.semantic`)

### Failure behavior

If embedding fails (provider error, timeout, or dimension mismatch):

- Do not upsert vectors for that object
- Emit `index.embedding.failed` with:
  - `expected_dim`
  - `actual_dim` (when known)
  - provider/model
  - source ref / note path
  - error string

This event is the canonical signal to operators that the embedding chain is misconfigured or has drifted.

## Storage: VectorIndex

VectorIndex stores embeddings as derived data:

- keyed by object UUID + view + chunk identifier (implementation detail)
- includes recorded embedding identity/provenance
- supports similarity search

VectorIndex must be treated as rebuildable cache: if identity changes, vectors are invalid until rebuilt.

## Operational guardrails

Recommended operational checks:

- `/api/health` should confirm:
  - ollama reachable
  - configured models visible
- Index preflight (if enabled) should warn on:
  - identity drift
  - missing or inconsistent dims
- `index doctor` should detect:
  - runtime identity != stored identity
  - mismatched vector dimensions in storage

## Troubleshooting: dimension mismatch

If you see errors like:

- `expected_dim: 768`
- `actual_dim: 1536`
- `embedding dim mismatch ...`

Do the following:

1. Confirm what the provider actually returns for the configured model:
   - run a single embedding probe using the same backend + model name.
2. Ensure runtime config matches that reality:
   - set `EMBED_DIM` to the provider’s real output dimension
   - confirm `EMBED_MODEL` is the intended model
3. Rebuild the vector index if identity changed:
   - embeddings are not forward-compatible across identity changes.

Common causes:
- `EMBED_MODEL` points to a different model than intended
- the model version/tag changed upstream
- mixed environments (host vs container) calling different ollama instances

## Change policy

- Any change to the embedding identity must be:
  - explicitly recorded in docs/steering,
  - verified via doctor/preflight,
  - followed by a vector-index rebuild (or a controlled migration).

