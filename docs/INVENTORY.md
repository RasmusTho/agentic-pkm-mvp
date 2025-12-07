State: SoT v4.10 Reality-MVP (current core).
# Runtime Inventory

Single source of truth for configuration, dependencies, and operational contracts. Update in the same PR as related code or CI changes.

<!-- SECTION:INVENTORY:BEGIN -->
## Environment variables
| Variable | Location (file:line) | Default | Effect |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | app/agents/qa/agent.py:20, app/llm/adapter.py:4 | `ollama` (CLI fallback in `app/cli.py:24` sets `mock`) | Selects QA-agent / embedding / CLI backend (`ollama`, `mock`, `openai`, `deepseek`). |
| `LLM_MOCK_RESPONSE` | app/agents/qa/agent.py:27, app/cli.py:25 | `Mock response [#1]` or CLI default JSON | Response returned whenever `LLM_PROVIDER=mock`. |
| `LLM_MAX_TOKENS` | app/agents/qa/agent.py:13 | `512` | Caps QA answers when Ollama is active. |
| `LLM_TIMEOUT` | app/agents/qa/agent.py:41, app/llm/embeddings.py:37, app/llm/adapter.py:20 | `120` s (chat); `60` s (embeddings / other HTTP) | HTTP timeout for Ollama / OpenAI / DeepSeek. |
| `OLLAMA_HOST` / `OLLAMA_URL` | app/agents/qa/agent.py:31, app/llm/embeddings.py:10 | `http://127.0.0.1:11434` | Base URL for `/api/chat` and `/api/embeddings`; `OLLAMA_URL` overrides host. |
| `OLLAMA_MODEL` | app/agents/qa/agent.py:32 | `llama3.1:8b-instruct` | Default QA model. |
| `OLLAMA_EMBED_MODEL` / `EMBED_MODEL` | app/llm/embeddings.py:11 | `nomic-embed-text:latest` | Embedding model for `/api/embeddings`. |
| `LLM_MODEL` / `LLM_REASONING_MODEL` | app/llm/adapter.py:5-6 | `llama3.1:8b` | Used by the classifier adapter; reasoning flavor via `LLM_REASONING_MODEL`. |
| `OPENAI_API_KEY`, `OPENAI_BASE` | app/llm/adapter.py:26-33 | – / `https://api.openai.com/v1/chat/completions` | Required when `LLM_PROVIDER=openai`. |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` | app/llm/adapter.py:38-44 | – / `https://api.deepseek.com/chat/completions` | Required when `LLM_PROVIDER=deepseek`. |
| `LLM_TEMPERATURE` | app/services/llm.py:69 | `0` | Temperature for `app/services/llm.py` callers outside QA. |
| `INDEX_OUTBOX_PATH` | app/index/outbox.py:12-20, app/cli.py:76 | `./tmp/index-outbox.jsonl` | File receiving ingestion/index events; must be writable (see health CLI). |
| `STORE_BACKEND` | app/cli.py:21, app/stores/provider.py:39 | `memory` | Selects ObjectStore backend (`memory` or `pg`). |
| `DATABASE_URL` | app/memory/store.py:16, app/stores/pg.py:21 | `postgresql+psycopg://app:app@127.0.0.1:15432/app` | Primary DSN for stores/agents/tests. |
| `MEMORY_ENABLED` | app/memory/store.py:23 | `true` | Disables the memory store when `false`. |
| `ASR_MODEL`, `ASR_DEVICE` | app/media/transcribe.py:71-72 | `base`, `auto` | faster-whisper model/device. |
| `ASR_COMPUTE_TYPE` | (hard-coded `int8` in app/media/transcribe.py:75) | `int8` | Not configurable yet (gap). |
| `EVENT_LOG` | app/services/events.py:4 | `events.jsonl` | Default audit/event log file. |
| `TRACE_LOG_PATH` | app/observability/trace_log.py:2 | `/tmp/trace.jsonl` | Output path when trace logging is enabled. |

## Span nodes (`@span`)
| Node | Location | Purpose | Extra fields |
| --- | --- | --- | --- |
| `transcribe` | app/media/transcribe.py:122 | Audio transcription (yt-dlp + ffmpeg + faster-whisper). | `extra` only populated on failure (e.g. `CalledProcessError`). |
| `agent.draft` | app/agents/qa/agent.py:59 | First LLM response + citation enforcement. | `_token_in/out` optional. |
| `agent.self_check` | app/agents/qa/agent.py:82 | Post-draft validation (references, length). | `extra` carries exception info. |
| `agent.finalize` | app/agents/qa/agent.py:109 | Adjustments before returning the answer. | None today. |
| `agent.answer` | app/agents/qa/agent.py:117 | Whole QA pipeline: retrieval → draft → self-check → finalize. | Logs retrieval failures in `extra`. |
| `health.check` | app/cli/health.py:49 | Local dependency checks + JSON output. | `extra.error` on exception; CLI contains full `checks`. |

## CLI surfaces
All commands run via `python -m app.cli <command>` (Click). `--json` switches to machine-readable output; `--trace-id` can be set manually.

| Command | Location | Description | Exit codes |
| --- | --- | --- | --- |
| `normalize SOURCE [--json --trace-id]` | app/cli/__init__.py:34-55 | Materialize file/URL, run the normalizer, emit the core object. | 0 on success, `FileNotFoundError` bubbles → exit 1. |
| `classify OBJECT_ID [--json --trace-id]` | app/cli/__init__.py:57-74 | Classify an existing normalized object. | 0 on success, exception if object missing. |
| `transcribe SOURCE [--json --trace-id]` | app/cli/__init__.py:76-94 | yt-dlp → ffmpeg → faster-whisper; writes an index-outbox entry (`kind=transcript`). | 0 on success, ffmpeg/yt-dlp errors → 1. |
| `pipe SOURCE [--json --trace-id]` | app/cli/__init__.py:96-133 | Normalize → classify (+transcribe when audio/URL) and write aggregated JSONL. | 0 on success, exit 1/2 on missing sources. |
| `health [--json --trace-id]` | app/cli/__init__.py:135-147, app/cli/health.py | Local dependency checks (ffmpeg, yt-dlp, INDEX_OUTBOX_PATH, Ollama reachability). | 0 when `ok=true`, otherwise 1. |

## External tools and network calls
- **yt-dlp** – downloads audio / m4a (`app/media/transcribe.py:22-39`).
- **ffmpeg** – converts arbitrary formats to 16 kHz mono wav (`app/media/transcribe.py:47-65`).
- **faster-whisper** – local ASR with `_MODEL_CACHE` (`app/media/transcribe.py:68-99`).
- **Ollama** – `/api/chat` and `/api/embeddings` (`app/agents/qa/agent.py:31-48`, `app/llm/embeddings.py:34-43`).
- **httpx / requests** – also used for OpenAI/DeepSeek (`app/llm/adapter.py:16-47`).

## Index-outbox JSONL schema
Defined in `app/index/outbox.py:28-58`. Each line contains at least:
```json
{
  "object_id": "uuid4",
  "kind": "transcript|note|pipeline",
  "source_ref": "path-or-url",
  "payload": {
    "text": "...",
    "segments": [],
    "language": "sv"
  },
  "embedding": null,
  "topic": null
}
```
Transcribe entries (`app/media/transcribe.py:102-134`) also include `trace_id` before returning. `append_jsonl` always writes a newline and attempts to fan text into the in-memory retrieval store (`app/retrieval/hybrid.py:28-112`).

## Errors & edge cases
- **YouTube anti-bot (403/429)** – `YoutubeDL.extract_info` raises `DownloadError`; CLI surfaces the exception. Use cookies or alternate hosts (see `docs/DEPENDENCIES.md`). (`app/media/transcribe.py:36-38`)
- **Missing ffmpeg** – `subprocess.run(..., check=True)` raises `CalledProcessError`; health CLI flags the same issue (`app/media/transcribe.py:54-65`, `app/cli/health.py:20-28`).
- **Missing yt-dlp** – Import error during module load; health CLI signals it (`app/media/transcribe.py:10-15`, `app/cli/health.py:30-36`).
- **ASR model not installed** – `faster-whisper` raises; message instructs how to install (`app/media/transcribe.py:68-82`).
- **Ollama offline** – QA and health CLI report `requests.ConnectionError` / `httpx` failures with host info (`app/agents/qa/agent.py:31-48`, `app/cli/health.py:38-49`).
- **`INDEX_OUTBOX_PATH` unwritable** – `append_jsonl` raises and the health CLI test write fails (`app/index/outbox.py:28-58`, `app/cli/health.py:30-36`).

## Cache, timeout, and breaker policy
- `_MODEL_CACHE` keeps `(ASR_MODEL, ASR_DEVICE)` → `WhisperModel` (`app/media/transcribe.py:19-76`). No eviction; restart to free memory.
- `_embed_single` is `@lru_cache(maxsize=512)` and reuses embeddings per text/provider/model (`app/llm/embeddings.py:27-43`).
- `LLM_TIMEOUT` governs Ollama/OpenAI/DeepSeek HTTP calls (60–120 s). No automatic retry yet; see `docs/LLM_BACKENDS.md`.
- `CircuitBreaker` and `timeout_wrapper` live in `app/quality/guardrails.py:32-61`; mostly used outside QA today (gap documented).
- Span logging always includes latency in ms and `status` (`app/obs/log.py:20-58`), powering the `jq` recipes in `docs/OBSERVABILITY.md`.
<!-- SECTION:INVENTORY:END -->
