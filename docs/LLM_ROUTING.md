State: SoT v5.x forward line (router + fabric contract)

LLM Routing Contract (Router + Fabric)

This document defines the canonical LLM access layer for chat/completions and embeddings.
The router chooses a route (provider/model/mode), and the fabric is the only allowed entrypoint
for high-level modules to talk to LLMs.

## Concepts

- **Router**: Deterministic route selector. Produces `LLMRoute {provider, model, mode, reason, degraded}`
  from `LLMTaskIntent`. It is pure and environment-driven.
- **Fabric**: Runtime entrypoint that binds a route to an actual client. It exposes:
  - `get_chat_client(LLMTaskIntent)` → `ChatClient` with `.chat(...)`
  - `get_embeddings_client(LLMTaskIntent)` → embedding client with `.embed_text(...)`
- **Routes/Providers**: A route selects a provider + model. Providers are identified by string values
  (`mock`, `ollama`, `openai`, `deepseek`, etc.).
- **Deterministic routing**: If `determinism_required=True`, the router prefers `mock` over non-deterministic providers.
- **Default route reporting**: The fabric exposes `describe_default_routes()` so health checks can report
  the active defaults.

## Configuration precedence

Routing is intentionally deterministic and single-source:

1) **Vault-first config (stub)** — this is reserved for a future settings compiler integration.
   The router currently does not read vault settings directly.
2) **Environment overrides** — env vars override defaults (see below).
3) **Built-in defaults** — used when no overrides are present.

Until vault-first routing is wired, use env vars to control routes in the runtime and CI.

## Supported environment variables

Core routing:
- `LLM_PROVIDER` — default provider (`mock`, `ollama`, `openai`, `deepseek`).
- `LLM_MODEL` — default chat/completions model.
- `EMBED_MODEL` / `OLLAMA_EMBED_MODEL` — embedding model name for embed routes.
- `LLM_FORCE_PROVIDER` — hard override for router provider (all tasks).
- `LLM_FORCE_MODEL` — hard override for router model (all tasks).

Provider-specific:
- `OLLAMA_HOST` / `OLLAMA_URL` — base URL for Ollama native APIs.
- `OPENAI_API_KEY`, `OPENAI_BASE` — OpenAI API auth + base URL.
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` — DeepSeek API auth + base URL.

Optional tuning:
- `LLM_TIMEOUT` — HTTP timeout (seconds).
- `LLM_TEMPERATURE` — chat temperature for Ollama/native calls.
- `LLM_MAX_TOKENS` — token budget used by the fabric caller.
- `LLM_MOCK_RESPONSE` — deterministic mock response payload for `mock` provider.

### Examples

```bash
# Deterministic local run
export LLM_PROVIDER=mock
export LLM_MOCK_RESPONSE='{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

# Ollama chat + embeddings
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1:8b
export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_EMBED_MODEL=nomic-embed-text:latest

# Force a specific model for all LLM calls
export LLM_FORCE_PROVIDER=ollama
export LLM_FORCE_MODEL=llama3.1:8b-instruct
```

## How to debug routing

- **Health snapshot** (`/api/health`)
  - `checks.llm_router.selected_defaults` shows the router’s default routes.
  - `checks.llm_providers.providers` lists provider health checks.
- **Alpha status output** (`scripts/alpha_status.py`)
  - Prints `llm routes` and `llm providers` summaries for human operators.

## Non-goals / future work

- Vault-first settings compiler integration for LLM routes is planned but not yet wired.
- Per-task routing policies (budget/latency-aware switching, provider pools) are deferred.
- Multi-provider load balancing and rate limit handling are out of scope for the current fabric.
