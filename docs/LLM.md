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

Embeddings configuration is separate from chat:

- `EMBED_MODEL`
  - Example: `nomic-embed-text:latest`
- `EMBED_DIM`
  - Example: `768`
  - Must match the provider’s actual output dimension.
  - If this changes, the embedding identity changes and the vector index must be rebuilt.

Optional:
- `EMBED_NORMALIZE` (if used)
  - Default behavior is normalized vectors.

## Runtime contract

- Chat calls should go through the LLM adapter layer.
- Embedding calls must go through the provider-aware embedding helper (see `docs/EMBEDDINGS.md`).

## Quick sanity checks

- `/api/health` should confirm ollama is reachable and lists models.
- If you see `index.embedding.failed` with a dim mismatch, validate:
  - `EMBED_MODEL` is correct
  - `EMBED_DIM` matches the provider output
  - you are calling the intended `OLLAMA_HOST` instance

