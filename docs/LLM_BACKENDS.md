State: SoT v5.5 baseline (descriptive). Backend support is implementation-defined; update this doc when env vars/endpoints change.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# LLM Backends

The QA agent and classifier can switch backends via environment variables. This document captures capabilities, timeouts, and planned improvements.

<!-- SECTION:LLM:BEGIN -->
## Supported backends
- **Mock** – `LLM_PROVIDER=mock`. Returns `LLM_MOCK_RESPONSE` and avoids network calls (`app/agents/qa/agent.py:24-28`, `app/llm/adapter.py:12-14`). Default in CI/tests.
- **Ollama** – Production default (`LLM_PROVIDER=ollama`). QA hits `/api/chat` (`app/agents/qa/agent.py:31-48`), embeddings use `/api/embeddings` (`app/llm/embeddings.py:34-43`). Requires the local Ollama daemon.
- **OpenAI & DeepSeek** – Routed through `app/llm/adapter.py:25-47`. Require API keys and are used by services calling `generate(...)`.

## Configuration
| Scenario | Variables | Notes |
| --- | --- | --- |
| Mock (CLI/tests default) | `LLM_PROVIDER=mock`, `LLM_MOCK_RESPONSE='{"type":"note", ...}'` | No network calls. Health check skips Ollama reachability. |
| Local Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_HOST=http://127.0.0.1:11434`, `OLLAMA_MODEL=llama3.1:8b-instruct`, `OLLAMA_EMBED_MODEL=nomic-embed-text:latest` | Pre-pull models (`ollama pull llama3.1:8b`). |
| DeepSeek via Ollama tag | `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=deepseek-r1:8b` | Same health flow. Pull via `ollama pull deepseek-r1:8b`. |
| OpenAI API | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL=gpt-4o-mini` | `LLM_TIMEOUT` defaults to 60 s; no built-in retry—wrap with `DEFAULT_BREAKER` if needed. |
| DeepSeek API | `LLM_PROVIDER=deepseek`, `DEEPSEEK_API_KEY=...`, `LLM_MODEL=deepseek-chat` | Reuses the same `LLM_TIMEOUT`. |

## Timeouts, retries, breakers
- `LLM_TIMEOUT` applies to every HTTP call (QA, embeddings, adapter). Defaults: 120 s for chat, 60 s for embeddings / other APIs.
- No automatic retry yet; the health CLI only verifies reachability.
- `app/quality/guardrails.DEFAULT_BREAKER` is available for future integration around `_call_llm`. See `docs/QUALITY.md`.
- For CLI safety, run with `LLM_PROVIDER=mock` until a local Ollama server is ready.

## DeepSeek via Ollama tag
- Pull the model locally: `ollama pull deepseek-r1:8b`.
- Set `OLLAMA_MODEL=deepseek-r1:8b` and tune `LLM_MAX_TOKENS` (DeepSeek responses are verbose; keep `max_tokens < 400`).
- Limitations: reasoning / chain-of-thought text is still returned verbatim; redact before logging (`docs/PRIVACY.md`).
<!-- SECTION:LLM:END -->
