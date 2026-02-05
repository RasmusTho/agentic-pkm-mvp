State: SoT v5.5 baseline (descriptive). This doc describes the env vars and endpoints used by the current LLM + embeddings adapters.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# LLM (Chat + Embeddings)

This document describes how the system selects/configures the LLM provider(s) used for:
- **Chat/completions** (classification, answering, panel helpers, etc.)
- **Embeddings** (retrieval/indexing)

For the normative embedding identity + rebuild contract, see `docs/EMBEDDINGS.md`.

## Providers (Current)
`LLM_PROVIDER` controls both chat and embeddings.

- `ollama` (default): chat via Ollama `/api/chat`; embeddings via Ollama `/api/embeddings` with fallback to `/v1/embeddings`.
- `mock`: deterministic, no network calls.
- `openai`: chat via OpenAI-compatible Chat Completions API.
- `deepseek`: chat via DeepSeek API.

## Core Environment Variables (Current Reality)

### Common
- `LLM_PROVIDER` (default: `ollama`)
- `LLM_MODEL` (default: `llama3.1:8b`) used for chat/completions
- `LLM_REASONING_MODEL` (default: `LLM_MODEL`) used when callers request reasoning mode
- `LLM_TIMEOUT` (seconds)
  - chat defaults to 120s in `app/llm/adapter.py`
  - embeddings defaults to 60s in `app/llm/embeddings.py`

### Ollama (Chat)
- `OLLAMA_HOST` (default: `http://127.0.0.1:11434`)
  - Chat endpoint: `${OLLAMA_HOST}/api/chat`

### Ollama (Embeddings)
Embeddings are handled by `app/llm/embeddings.py`.

- Base URL:
  - `OLLAMA_URL` (preferred) or `OLLAMA_HOST` (fallback)
  - Both support an OpenAI-compat suffix; `.../v1` is normalized internally.
- Model:
  - `OLLAMA_EMBED_MODEL` or `EMBED_MODEL` (default: `nomic-embed-text:latest`)
- Dimensions:
  - `EMBED_DIM` (default: `1536`, pulled from settings when available)
  - `OLLAMA_EMBED_DIMENSIONS` controls whether we include `dimensions` in the payload (default: included).
- Endpoint:
  - Primary: `${OLLAMA_URL}/api/embeddings`
  - Fallback: `${OLLAMA_URL}/v1/embeddings`
- Normalization:
  - `app/embedding_config.py` applies L2 normalization by default in `embed_text()` unless callers opt out.

### Mock
- `LLM_MOCK_RESPONSE` controls the content returned by the chat adapter when `LLM_PROVIDER=mock`.

### OpenAI / DeepSeek (Chat)
- `OPENAI_API_KEY` (+ optional `OPENAI_BASE`, default `https://api.openai.com/v1/chat/completions`)
- `DEEPSEEK_API_KEY` (+ optional `DEEPSEEK_BASE`, default `https://api.deepseek.com/chat/completions`)

## Delta / Known Limits
- Embeddings are implemented for `mock` and `ollama` in the current code; `openai`/`deepseek` embeddings are not wired here today.
- Diagnostics note: `python -m app.cli llm check` uses `OPENAI_BASE_URL` (OpenAI-compatible base) rather than `OPENAI_BASE` (chat completions URL) when probing non-Ollama providers.
- If you change `EMBED_DIM`, you must treat it as an embedding identity change and rebuild any derived embedding stores (see `docs/EMBEDDINGS.md`).

## Quick Checks
- With Ollama running locally:
  - `OLLAMA_URL=http://127.0.0.1:11434 LLM_PROVIDER=ollama python -m app.cli llm check --strict`
- If embeddings fail:
  - confirm `EMBED_DIM` matches the provider output and that the model supports the requested dimension behavior
  - confirm the endpoint is reachable (`OLLAMA_URL` / `OLLAMA_HOST`)
