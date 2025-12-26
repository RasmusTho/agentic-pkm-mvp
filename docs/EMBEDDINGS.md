# Embeddings

State: Active (current).

This document is the **normative specification** for how embeddings are produced, validated, recorded, and stored in the system.

Embeddings are **derived artifacts** (rebuildable). The canonical source of truth remains the vault-backed Markdown + ObjectStore payloads.

## Goals

- One consistent embedding pipeline across runtime (API/worker) that honors configuration:
  - `LLM_PROVIDER`
  - `OLLAMA_HOST`
  - `EMBED_MODEL`
  - `EMBED_DIM`
  - `EMBED_NORMALIZE` (if present; defaults to normalized vectors)
- A stable **embedding identity** recorded alongside vectors so we can detect drift.
- Clear operational behavior for dimension mismatch, model swaps, and rebuilds.
- **Steering doc alignment**: any embedding-identity change MUST be reflected in steering docs (see Change Policy).

## High-level flow

1. Content is prepared for indexing (e.g., markdown semantic view).
2. Indexer resolves the **embedding identity** up-front.
3. Indexer calls the provider-aware embedding helper (`llm_embed_text`) with:
   - provider / base URL (via env + provider logic)
   - model name
   - expected dimension (guardrail)
   - normalize flag
   - (optional) query/document mode formatting when required by the model family
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
  - Example (default local): `nomic-embed-text:latest`
- `EMBED_DIM`
  - Example for `nomic-embed-text:latest`: `768`
  - Used as a **guardrail**. If provider returns a different dim, indexing fails for that object and an error event is emitted.

### Optional env vars

- `EMBED_NORMALIZE`
  - Default behavior is to return **normalized** vectors unless explicitly disabled.
  - Changing normalization changes the embedding identity and requires rebuilding the vector index.

## Query vs Document embeddings (RAG invariant)

The system MUST use the same embedding **identity** for:
- document/chunk embeddings at index time
- query embeddings at retrieval time (ASK)

If identity differs, similarity scores become meaningless and retrieval quality collapses.

The ASK/retrieval path MUST call the same `llm_embed_text` helper (or a shared wrapper) and record/verify the identity via doctor/preflight.

## Model-specific formatting (query/passage prefixes)

Some embedding model families require input formatting such as:
- `query: ...`
- `passage: ...`

If/when such a model is used, the embedding layer MUST apply the correct formatting based on a `mode` (query vs document) parameter.

Default for `nomic-embed-text` is “no special prefix”.

## Distance metric and normalization

We standardize on **cosine-style semantic similarity**.

- If vectors are normalized, cosine similarity is equivalent to inner-product ordering.
- If vectors are not normalized, cosine distance must be computed directly.

VectorIndex and the Postgres/pgvector schema MUST be configured consistently with this choice (operator class / metric). Any change here is an identity change and requires rebuild.

## Embedding identity

The system maintains a stable identity record resolved by `get_embedding_identity()` and should include (at minimum):

- provider (e.g., `ollama`)
- model (e.g., `nomic-embed-text:latest`)
- expected dimension (e.g., `768`)
- normalize flag (e.g., `true`)
- (optional) formatting mode policy version (if query/passage rules apply)

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
- formatting policy (query/passage rules)

…then previously stored vectors are not comparable. The correct operation is to **rebuild** the vector index under the new identity.

## Call graph (runtime)

Normative call path:

- Indexer (worker/runtime) imports `llm_embed_text` from `app.index.embeddings`
- `app.index.embeddings.llm_embed_text(...)` routes to the provider-aware embedding implementation in `app.llm.embeddings.embed_text(...)`
- Provider logic uses `LLM_PROVIDER` and `OLLAMA_HOST` to decide how to call the backend.

> **Note:** When `LLM_PROVIDER=ollama`, the runtime calls Ollama’s native `/api/embed` endpoint with `{model, input, dimensions, truncate: true}`. We only fall back to the OpenAI-compatible `/api/embeddings` mode when that compatibility layer is explicitly enabled on the Ollama daemon.

Indexer MUST NOT call deterministic/test-only helpers in production paths.

## Indexing behavior and invariants

### Success

For each object:
- produce one or more vectors (depending on chunking/view)
- upsert vectors into VectorIndex
- emit `index.object.embedded` with:
  - object id
  - counts (vectors)
  - provenance (provider/model/identity)
  - view (e.g., `markdown.semantic`)
  - actual_dim (record what we got back)

### Failure

If embedding fails (provider error, timeout, or dimension mismatch):

- do not upsert vectors for that object
- emit `index.embedding.failed` with:
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

VectorIndex is rebuildable cache: if identity changes, vectors are invalid until rebuilt.

## Operational guardrails

Recommended checks:
- `/api/health` confirms backend reachable and models visible
- Index preflight warns on:
  - identity drift
  - missing/inconsistent dims
- `index doctor` detects:
  - runtime identity != stored identity
  - mismatched vector dimensions in storage

## Rebuild playbook (when identity changes)

1) Update configuration (`EMBED_MODEL`, `EMBED_DIM`, `EMBED_NORMALIZE`) and steering docs.
2) Run doctor/preflight to confirm runtime identity is stable.
3) Rebuild VectorIndex (clear + re-embed) using the project’s supported CLI/tooling.
4) Verify:
   - no `index.embedding.failed`
   - stored identity matches runtime identity
   - retrieval/ASK uses the same identity

## Change policy (steering docs)

Any change to the embedding identity MUST:
- be recorded in steering docs (at minimum `docs/LLM.md` and this document),
- be verified via doctor/preflight,
- be followed by a VectorIndex rebuild (or a controlled migration).
