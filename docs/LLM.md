State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Operational provider/setup guide for current chat and embedding adapters; routing/fabric contract remains in `docs/LLM_ROUTING.md` and embedding identity rules remain in `docs/EMBEDDINGS.md`.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# LLM (Chat + Embeddings)

This document describes how the system selects/configures the LLM provider(s) used for:
- **Chat/completions** (classification, answering, panel helpers, etc.)
- **Embeddings** (retrieval/indexing)

For the normative embedding identity + rebuild contract, see `docs/EMBEDDINGS.md`.
For routing precedence and fabric behavior, see `docs/LLM_ROUTING.md`.

## Providers (Current)
`LLM_PROVIDER` controls chat and is the **fallback** source for the embedding provider.
The embedding provider is selected by `EMBED_PRIMARY_PROVIDER` (env) when set, otherwise
`LLM_PROVIDER`; see `docs/EMBEDDINGS.md :: Configuration` for the full precedence and the
`EMBED_FALLBACK_PROVIDER` knob.

- `ollama` (default): chat via Ollama `/api/chat`; embeddings via Ollama `/api/embeddings` with fallback to `/v1/embeddings`.
- `mock`: deterministic, no network calls.
- `openai`: chat via OpenAI-compatible Chat Completions API.
- `deepseek`: chat via DeepSeek API.

> **Planned (not yet usable):** `gemini` is a recognized embedding-provider *selection* value, but its adapter is not yet registered in `app/llm/embeddings.py::PROVIDER_REGISTRY`. Setting `EMBED_PRIMARY_PROVIDER=gemini` today fails with `Unsupported embedding provider`. The accepted posture (`docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`) is Ollama-primary with a **dimension-matched (768)** Google Gemini (`gemini-embedding-001` @ `output_dimensionality=768`, L2-renormalized) auto-fallback consulted on primary failure; the fallback write is **MIXED-IDENTITY / reconcilable** (carries the Gemini identity, reconciled via `index reconcile` once Ollama recovers; the query path always uses the primary identity — `docs/EMBEDDING_RELIABILITY/README.md` CTI-1/2/3). The adapter lands in the Embedding Reliability capability (issue #2292; runtime wiring tracked by #2296/#2297); see `docs/EMBEDDINGS.md :: Configuration` and `:: Fallback rule` for provider selection and the fallback contract.

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
  - `EMBED_DIM` (documented default: `768`, matching `nomic-embed-text`'s native dimension and the dimension-matched Gemini `gemini-embedding-001` @ 768 fallback per `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`; the guardrail is enforced for every provider — `docs/EMBEDDING_RELIABILITY/README.md` CTI-1). The in-code `DEFAULT_EMBED_DIM`/`settings.embed_dim` constant still reads `1536` pending the runtime change in #2296/#2297, so an operator on `nomic-embed-text` must set `EMBED_DIM=768` explicitly today. This is the configured guardrail dimension. The runtime includes a `dimensions` payload field, but the legacy `/api/embeddings` endpoint (the primary call below) ignores it — only `/api/embed` honors `dimensions` — so the vector keeps the model's native size and `EMBED_DIM` must be set to match it; it does not resize the vector. See `docs/EMBEDDINGS.md` for the identity/guardrail contract.
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

## Backend scenarios

| Scenario | Variables | Notes |
| --- | --- | --- |
| Mock (CLI/tests default) | `LLM_PROVIDER=mock`, `LLM_MOCK_RESPONSE='{"type":"note", ...}'` | No network calls. Health check skips Ollama reachability. |
| Local Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_HOST=http://127.0.0.1:11434`, `LLM_MODEL=llama3.1:8b-instruct`, `OLLAMA_EMBED_MODEL=nomic-embed-text:latest` | Pre-pull models (`ollama pull llama3.1:8b`). |
| DeepSeek via Ollama tag | `LLM_PROVIDER=ollama`, `LLM_MODEL=deepseek-r1:8b` | Same health flow. Pull via `ollama pull deepseek-r1:8b`. |
| OpenAI API | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL=gpt-5.4-mini` | Current lower-latency default. Use `gpt-5.4` for heavier reasoning/coding flows. No built-in retry; consider guardrail breaker integration for unstable remote providers. |
| DeepSeek API | `LLM_PROVIDER=deepseek`, `DEEPSEEK_API_KEY=...`, `LLM_MODEL=deepseek-chat` | Reuses the same timeout model as other chat providers. |

## Timeouts, retries, breakers

- `LLM_TIMEOUT` applies to every HTTP call.
  - chat defaults to 120s
  - embeddings and other adapter calls default to 60s
- No automatic retry is implemented today; the health CLI only checks reachability/basic readiness.
- `app/quality/guardrails.DEFAULT_BREAKER` is available for future integration around provider calls.
- For deterministic CLI/test workflows, prefer `LLM_PROVIDER=mock` until a local Ollama server or remote provider is confirmed healthy.

## Delta / Known Limits
- Embeddings are implemented for `mock` and `ollama` in the current code; `openai`/`deepseek` embeddings are not wired here today.
- Diagnostics note: `python -m app.cli llm check` uses `OPENAI_BASE_URL` (OpenAI-compatible base) rather than `OPENAI_BASE` (chat completions URL) when probing non-Ollama providers.
- If you change `EMBED_DIM`, you must treat it as an embedding identity change and rebuild any derived embedding stores (see `docs/EMBEDDINGS.md`).
- DeepSeek via Ollama remains effectively an Ollama deployment choice rather than a separate provider integration.
- Routing policy and provider/model selection precedence live in `docs/LLM_ROUTING.md`; keep that document separate from this operational setup guide.

## DeepSeek via Ollama tag

- Pull the model locally: `ollama pull deepseek-r1:8b`
- Set `LLM_MODEL=deepseek-r1:8b`
- Keep token budgets conservative for verbose reasoning-style output
- Treat chain-of-thought style output as sensitive and avoid logging it directly; see `docs/PRIVACY.md`

## Quick Checks
- With Ollama running locally:
  - `OLLAMA_URL=http://127.0.0.1:11434 LLM_PROVIDER=ollama python -m app.cli llm check --strict`
- If embeddings fail:
  - confirm `EMBED_DIM` matches the provider output and that the model supports the requested dimension behavior
  - confirm the endpoint is reachable (`OLLAMA_URL` / `OLLAMA_HOST`)
- For routing/debugging questions:
  - use `docs/LLM_ROUTING.md`
  - inspect health/status surfaces that report selected defaults and provider readiness
