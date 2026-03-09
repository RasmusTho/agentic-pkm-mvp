State: SoT v5.5 baseline (descriptive). This is a reference inventory; if any row drifts from code, prefer the code and update this doc.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Runtime Inventory

Reference inventory for configuration, dependencies, and operational contracts. Update in the same PR as related code or CI changes.

<!-- SECTION:INVENTORY:BEGIN -->
## Environment variables
| Variable | Used in (module) | Default | Effect |
| --- | --- | --- | --- |
| `VAULT_ROOT` | worker/watcher/cli | (none) | Path to the live vault root for watcher/ingest flows. |
| `VAULT_LAYOUT_NOTE_REL` | `app/vault/layout.py` | (none) | Disambiguate which `vault.layout.md` to load when multiple exist. |
| `VAULT_SYSTEM_DIR_REL` / `VAULT_INBOX_DIR_REL` / `VAULT_DESK_DIR_REL` | `app/vault/layout.py`, `app/vault/paths.py` | (none) | Folder hints; used when generating/validating layout or resolving paths. |
| `LLM_PROVIDER` | `app/llm/adapter.py`, `app/llm/embeddings.py` | `ollama` | Selects chat/embedding backend (`ollama`, `mock`, `openai`, `deepseek`). |
| `LLM_MODEL` / `LLM_REASONING_MODEL` | `app/llm/adapter.py` | `llama3.1:8b` | Chat model; reasoning flavor via `LLM_REASONING_MODEL`. |
| `LLM_MOCK_RESPONSE` | `app/llm/adapter.py` | `UNSURE` | Returned when `LLM_PROVIDER=mock`. |
| `LLM_TIMEOUT` | `app/llm/adapter.py`, `app/llm/embeddings.py` | `120` s (chat); `60` s (embeddings) | HTTP timeouts for provider calls. |
| `OLLAMA_HOST` / `OLLAMA_URL` | `app/llm/adapter.py`, `app/llm/embeddings.py` | `http://127.0.0.1:11434` | Base URL for Ollama chat + embeddings. |
| `OLLAMA_EMBED_MODEL` / `EMBED_MODEL` | `app/llm/embeddings.py` | `nomic-embed-text:latest` | Embedding model for `/api/embeddings`. |
| `EMBED_DIM` | `app/embedding_config.py` | `1536` | Expected embedding dimension (identity). |
| `OPENAI_API_KEY`, `OPENAI_BASE` | `app/llm/adapter.py` | – / OpenAI chat URL | Required when `LLM_PROVIDER=openai`. |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` | `app/llm/adapter.py` | – / DeepSeek chat URL | Required when `LLM_PROVIDER=deepseek`. |
| `INDEX_OUTBOX_PATH` | watcher/cli (`app/outbox/events.py`, `app/index/outbox.py`) | `tmp/index-outbox.jsonl` | JSONL audit log (non-canonical); watcher may append for diagnostics. |
| `DATABASE_URL` / `DB_DSN` | `app/services/outbox.py`, runtime | (none) | DB connection string (required when DB outbox is enabled/required). |
| `STORE_BACKEND` | watcher/runtime (`app/watcher/registry.py`) | `memory` | Controls some watcher gating/requirements. |
| `WATCHER_SCOPE_GLOB` | `app/watcher/registry.py` | `<inbox>/**` | Restricts watcher scanning scope. |
| `WATCHER_AUTO_EXEC` | `app/watcher/registry.py` | `1` | Auto-exec mode switch (`0` keeps emit-only mode). |
| `WATCHER_REQUIRE_DB_OUTBOX` | `app/watcher/registry.py` | `0` | When true, watcher refuses to run without DB outbox env present. |
| `WATCHER_RATE_LIMIT_PER_MIN` | `app/watcher/registry.py` | `30` | Rate limit for events emitted per minute. |
| `WATCHER_DEBOUNCE_MS` | `app/watcher/registry.py` | `1500` | Debounce window before scanning again. |

## Span nodes (`@span`)
| Node | Location (module) | Purpose | Extra fields |
| --- | --- | --- | --- |
| `transcribe` | `app/media/transcribe.py` | Audio transcription (yt-dlp + ffmpeg + faster-whisper). | `extra` only populated on failure. |
| `agent.answer` | `app/agents/qa/agent.py` | QA pipeline: retrieval → draft → self-check → finalize. | Logs retrieval failures in `extra`. |
| `health.check` | `app/cli/health.py` | Local dependency checks + JSON output. | `extra.error` on exception. |

## CLI surfaces
All commands run via `python -m app.cli <command>` (Click). `--json` switches to machine-readable output; `--trace-id` can be set manually.

| Command | Location | Description | Exit codes |
| --- | --- | --- | --- |
| `normalize SOURCE [--json --trace-id]` | app/cli/__init__.py:34-55 | Materialize file/URL, run the normalizer, emit the core object. | 0 on success, `FileNotFoundError` bubbles → exit 1. |
| `classify OBJECT_ID [--json --trace-id]` | app/cli/__init__.py:57-74 | Classify an existing normalized object. | 0 on success, exception if object missing. |
| `transcribe SOURCE [--json --trace-id]` | app/cli/__init__.py:76-94 | yt-dlp → ffmpeg → faster-whisper; writes an index-outbox audit entry (`kind=transcript`). | 0 on success, ffmpeg/yt-dlp errors → 1. |
| `pipe SOURCE [--json --trace-id]` | app/cli/__init__.py:96-133 | Normalize → classify (+transcribe when audio/URL) and write aggregated JSONL audit log. | 0 on success, exit 1/2 on missing sources. |
| `health [--json --trace-id]` | app/cli/__init__.py:135-147, app/cli/health.py | Local dependency checks (ffmpeg, yt-dlp, INDEX_OUTBOX_PATH, Ollama reachability). | 0 when `ok=true`, otherwise 1. |

## External tools and network calls
- **yt-dlp** – downloads audio / m4a (`app/media/transcribe.py:22-39`).
- **ffmpeg** – converts arbitrary formats to 16 kHz mono wav (`app/media/transcribe.py:47-65`).
- **faster-whisper** – local ASR with `_MODEL_CACHE` (`app/media/transcribe.py:68-99`).
- **Ollama** – `/api/chat` and `/api/embeddings` (`app/agents/qa/agent.py:31-48`, `app/llm/embeddings.py:34-43`).
- **httpx / requests** – also used for OpenAI/DeepSeek (`app/llm/adapter.py:16-47`).

## Index-outbox JSONL schema
Defined in `app/index/outbox.py`. Each line contains at least:
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
Transcribe entries (`app/media/transcribe.py`) also include `trace_id` before returning. `append_jsonl` always writes a newline and attempts to fan text into the in-memory retrieval store (`app/retrieval/hybrid.py`).

## Errors & edge cases
- **YouTube anti-bot (403/429)** – `YoutubeDL.extract_info` raises `DownloadError`; CLI surfaces the exception. Use cookies or alternate hosts (see `docs/DEPENDENCIES.md`). (`app/media/transcribe.py`)
- **Missing ffmpeg** – `subprocess.run(..., check=True)` raises `CalledProcessError`; health CLI flags the same issue (`app/media/transcribe.py`, `app/cli/health.py`).
- **Missing yt-dlp** – Import error during module load; health CLI signals it (`app/media/transcribe.py`, `app/cli/health.py`).
- **ASR model not installed** – `faster-whisper` raises; message instructs how to install (`app/media/transcribe.py`).
- **Ollama offline** – QA and health CLI report HTTP failures with host info (`app/agents/qa/agent.py`, `app/cli/health.py`).
- **`INDEX_OUTBOX_PATH` unwritable** – `append_jsonl` raises and the health CLI test write fails (`app/index/outbox.py`, `app/cli/health.py`).

## Cache, timeout, and breaker policy
- `_MODEL_CACHE` keeps `(ASR_MODEL, ASR_DEVICE)` → `WhisperModel` (`app/media/transcribe.py`). No eviction; restart to free memory.
- `_embed_single` is `@lru_cache(maxsize=2048)` and reuses embeddings per text/provider/model (`app/llm/embeddings.py`).
- `LLM_TIMEOUT` governs Ollama/OpenAI/DeepSeek HTTP calls (60–120 s). No automatic retry yet; see `docs/LLM_BACKENDS.md`.
- `CircuitBreaker` and `timeout_wrapper` live in `app/quality/guardrails.py`; usage varies by subsystem.
- Span logging includes latency and status (`app/obs/log.py`), powering the `jq` recipes in `docs/OBSERVABILITY.md`.
<!-- SECTION:INVENTORY:END -->
