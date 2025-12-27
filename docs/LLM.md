State: Active (current).
# LLM

This doc describes how the system selects and configures the LLM provider(s) used for **chat/completions** and **embeddings**.

For the detailed, end-to-end embedding contract (identity, dimensions, failure events, rebuild rules), see:
- `docs/EMBEDDINGS.md`

## Providers

Supported `LLM_PROVIDER` values:

- `ollama` (default in local/dev): uses `OLLAMA_HOST`
- `mock`: deterministic mock behavior for tests/CI

## Core configuration

### Common

- `LLM_PROVIDER`
  - Example: `ollama`

### Ollama

- `OLLAMA_HOST`
  - Example: `http://host.docker.internal:11434`
- `LLM_MODEL` (chat)
  - Example: `llama3.1:8b`

### Embeddings

Embeddings configuration is separate from chat;
- Default local plan:
  - `EMBED_MODEL=nomic-embed-text:latest`
  - `EMBED_DIM=768`
  - `EMBED_NORMALIZE=1` (normalized vectors by default)
- `EMBED_MODEL`
  - Example: `nomic-embed-text:latest`
- `EMBED_DIM`
  - Example: `768`
  - Must match the provider’s actual output dimension. If this changes, the embedding identity changes and the VectorIndex must be rebuilt.
- When `LLM_PROVIDER=ollama`, the runtime posts to the Ollama-native `/api/embed` endpoint with `{model, input, dimensions, truncate: true}`; the OpenAI-compatible `/api/embeddings` path is only used when that compatibility layer is explicitly enabled on the daemon.

Optional:
- `EMBED_NORMALIZE`
  - Default behavior is normalized vectors; disabling it changes the embedding identity.

## Runtime contract

- Chat calls should go through the LLM adapter layer.
- Embedding calls must go through the provider-aware embedding helper (see `docs/EMBEDDINGS.md`).

## Quick sanity checks

- `/api/health` should confirm ollama is reachable and lists models.
- If you see `index.embedding.failed` with a dim mismatch, validate:
  - `EMBED_MODEL` is pointing at `nomic-embed-text:latest` (or the chosen model)
  - `EMBED_DIM` matches the provider output (768 for the default model)
  - You are calling the intended `OLLAMA_HOST` instance
