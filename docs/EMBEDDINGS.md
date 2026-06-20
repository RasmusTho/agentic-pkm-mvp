State: SoT v5.5 baseline (normative embedding spec).
# Embeddings

This document is the **normative specification** for how embeddings are produced, validated, recorded, and stored in the system.

Embeddings are **derived artifacts** (rebuildable). The canonical source of truth remains the vault-backed Markdown + ObjectStore payloads.

## Goals

- One consistent embedding pipeline across runtime (API/worker) that honors configuration:
  - `vault/@Settings/llm_routing.md` / `runtime/settings/llm_routing.yaml`
  - `LLM_PROVIDER`
  - `OLLAMA_HOST` / `OLLAMA_URL`
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

Embedding provider/model choice is a user setting first, not a hidden runtime default. The preferred embedding route
comes from the compiled task policy; env vars supply defaults only when the policy leaves a field unset.

### Required / primary env vars

- `LLM_PROVIDER`
  - Supported: `ollama`, `mock` (registry providers also include `gemini`, `deterministic`).
  - Used as the **fallback** primary-provider source when `EMBED_PRIMARY_PROVIDER` is unset.
- `EMBED_PRIMARY_PROVIDER`
  - The primary embedding provider used for normal dispatch. Precedence: `EMBED_PRIMARY_PROVIDER` (env) > embedding-profile `primary_provider` > profile `provider` > `LLM_PROVIDER`. When unset, behavior is unchanged (falls back to `LLM_PROVIDER`).
  - Setting this changes the embedding **identity** (provider) and therefore requires a vector-index rebuild — see *Change policy* and the re-index path.
- `EMBED_FALLBACK_PROVIDER`
  - Optional secondary provider consulted only on primary-provider failure (read by the fallback orchestration; the registry slice only wires selection). A dimension-matched fallback is required — see the disciplined-fallback / re-index path tracked by the Embedding Reliability capability (issue #2292) and the *Fallback rule* section below.
- `OLLAMA_HOST`
  - Example: `http://host.docker.internal:11434`
- `EMBED_MODEL`
  - Example (default local): `nomic-embed-text:latest`
- `EMBED_DIM`
  - Runtime guardrail default: `1536` (`DEFAULT_EMBED_DIM` in `app/embedding_config.py`, mirrored by `settings.embed_dim`). This is the **configured/requested** dimension the runtime asserts against.
  - Relationship to the model's native dimension: `nomic-embed-text` emits `768` natively. The runtime includes a `dimensions` field in the Ollama payload (see Call graph), but the **legacy** `/api/embeddings` endpoint ignores it (only `/api/embed` honors `dimensions`), so the returned vector stays at the model's native size. The guardrail asserts the returned length matches `EMBED_DIM`, so `EMBED_DIM` must be set to the model's native dimension (`768` for `nomic-embed-text`) — it does **not** resize the vector. A mismatch (e.g. native `768` vs the runtime default `1536`) fails indexing for that object.
  - Used as a **guardrail**. If the provider returns a vector whose length differs from `EMBED_DIM`, indexing fails for that object and an error event is emitted.

### Optional env vars

- `EMBED_NORMALIZE`
  - Default behavior is to return **normalized** vectors unless explicitly disabled.
  - Changing normalization changes the embedding identity and requires rebuilding the vector index.
- `EMBED_MAX_INPUT_CHARS`
  - Character budget for a single embedding request. The embedding layer splits input above this budget into in-budget chunks, embeds each, and mean-pools the chunk vectors before storing, so an oversized note cannot exceed the model context window and 500 the request and **no tail content is dropped** from retrieval (see *Oversized input handling*).
  - Default: `6000` (inline default in `_embedding_max_input_chars`, `app/llm/embeddings.py`) — a conservative budget for `nomic-embed-text`'s ~2k-token context window. (The former `DEFAULT_EMBED_MAX_INPUT_CHARS` constant was removed in #2113.)
  - Set to `0` (or a negative value) to disable chunking entirely.
- `EMBED_RETRY_MAX`
  - Maximum number of attempts per object when transient embed failures occur (HTTP 5xx, EOF, connection-reset, timeout, 408, 429).
  - Default: `3`. Identical across dev, test, and prod — no environment-conditional branching.
- `EMBED_RETRY_BASE_BACKOFF_S`
  - Base sleep in seconds for exponential backoff between retry attempts. The sleep before attempt *n* is `min(base * 2^(n-1), EMBED_RETRY_MAX_BACKOFF_S)`.
  - Default: `1.0`. At default settings the sleeps are approximately 1 s and 2 s before the second and third attempts.
- `EMBED_RETRY_MAX_BACKOFF_S`
  - Cap on the backoff sleep in seconds.
  - Default: `30.0`.

Embedding execution is intentionally **serial** (one in-flight embed request at a time), including the batch `index rebuild` path. The bottleneck is a memory-bound shared Ollama, so concurrent embeds would compound the OOM this path exists to prevent; backpressure here means serialization + retry-with-backoff, not fan-out. There is deliberately **no concurrency knob**. If a remote provider later needs batch throughput, a bounded executor can be added scoped to that provider.

Per-object transient failures are retried with exponential **backoff** before `index.embedding.failed` is emitted. A single object failure never aborts the ingest of the remaining objects (see *Embedding Execution Queue*, `app/llm/embed_queue.py`).

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
- expected dimension (the configured `EMBED_DIM` guardrail; default `1536` — distinct from `nomic-embed-text`'s native `768`, see Configuration)
- normalize flag (e.g., `true`)
- (optional) formatting mode policy version (if query/passage rules apply)

This identity must be:
- resolved **before** embedding,
- recorded with the vector index metadata / provenance,
- attached to emitted indexing events.

### Fallback rule

Embeddings do not allow generic provider fallback. The runtime may:
- repair the endpoint for the chosen provider (for example, choose a Docker-reachable Ollama base URL),
- keep using the same provider/model/identity, and
- continue only if the resolved identity remains compatible.

The runtime must not silently switch to another embedding model/provider that changes provider, model, dimension, or normalization.
If the preferred embedding identity is unavailable and no compatible fallback exists, startup should fail or require index rebuild.

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
- Provider logic resolves the embedding provider via `EMBED_PRIMARY_PROVIDER` (falling back to `LLM_PROVIDER`) and uses `OLLAMA_HOST` to decide how to call the backend. Adapters are dispatched through the registry in `app/llm/embeddings.py::PROVIDER_REGISTRY`.

> **Note:** When `LLM_PROVIDER=ollama`, the runtime's **primary** embedding call is `${OLLAMA_URL}/api/embeddings` with `{model, prompt, dimensions}` (the `dimensions` field is included unless `OLLAMA_EMBED_DIMENSIONS` disables it). If that request fails, it **falls back** to the OpenAI-compatible `${OLLAMA_URL}/v1/embeddings` endpoint with `{model, input}`. This matches `app/llm/embeddings.py` and the endpoint table in `docs/LLM.md`.

Indexer MUST NOT call deterministic/test-only helpers in production paths.

## Indexing behavior and invariants

### Success

For each object:
- produce one or more vectors (depending on chunking/view)
- upsert vectors into VectorIndex
- purge the previous vectors for the UUID+view before writing when the same note is re-ingested with changed content, so duplicates can never remain
- emit `index.embedding.created` with (legacy alias: `index.object.embedded`):
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

### Oversized input handling

A single note must never abort the whole index build (#2110). The embedding layer applies two bounded defenses, in order:

1. **Chunking + mean-pooling to context budget.** Before each provider call, input longer than `EMBED_MAX_INPUT_CHARS` (default `6000`) is split into in-budget chunks; each chunk is embedded and the chunk vectors are mean-pooled into a single vector. This keeps every request within the model's context window so the provider does not return HTTP 500 ("input length exceeds the context length"), while preserving tail content rather than truncating it. Set `EMBED_MAX_INPUT_CHARS=0` to disable chunking.
2. **Per-item degradation.** When a single item still fails at the provider (e.g. truncation disabled, or another transient provider/HTTP error), `embed_texts` skips that item — it logs a warning and substitutes a zero vector of the correct `expected_dim` — instead of raising and aborting the remaining batch. The zero vector preserves the dimension guardrail and contributes no similarity signal.

Together these ensure an index build over a corpus containing one oversized or pathological note completes and the rest of the corpus embeds normally.

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
