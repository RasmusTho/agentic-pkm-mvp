State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Reference inventory of env vars, CLI surfaces, external tools, and runtime signals; code remains authoritative when a row drifts.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Runtime Inventory

Reference inventory for configuration, dependencies, and operational contracts. Update in the same PR as related code or CI changes.

<!-- SECTION:INVENTORY:BEGIN -->
## Environment variables

> **Superseded module note.** `app/llm/adapter.py` has zero runtime importers; it is **superseded**
> as the provider surface. `app/llm/embeddings.py::PROVIDER_REGISTRY` is likewise superseded as the
> adapter registry. The live canonical access layer for both chat and embeddings is
> `app/components/llm/` (`docs/COMPONENTS.md:95` — "LLM router + fabric"); high-level modules must
> use `get_chat_client` / `get_embeddings_client`, and
> `tests/architecture/test_import_rules.py::test_high_level_llm_access_uses_fabric` enforces the
> split. The rows below still name `app/llm/adapter.py` / `app/llm/embeddings.py` because those are
> the current physical locations of provider env-var parsing, not because they are the canonical
> access surface.

| Variable | Used in (module) | Default | Effect |
| --- | --- | --- | --- |
| `VAULT_ROOT` | worker/watcher/cli | (none) | Path to the live vault root for watcher/ingest flows. |
| `VAULT_LAYOUT_NOTE_REL` | `app/vault/layout.py` | (none) | Disambiguate which `vault.layout.md` to load when multiple exist. |
| `VAULT_SYSTEM_DIR_REL` / `VAULT_INBOX_DIR_REL` / `VAULT_DESK_DIR_REL` | `app/vault/layout.py`, `app/vault/paths.py` | (none) | Folder hints; used when generating/validating layout or resolving paths. |
| `LLM_PROVIDER` | `app/llm/adapter.py` (superseded, see note above), `app/llm/embeddings.py` (superseded, see note above) | `ollama` | Selects chat/embedding backend (`ollama`, `mock`, `openai`, `deepseek`). |
| `LLM_MODEL` / `LLM_REASONING_MODEL` | `app/llm/adapter.py` (superseded, see note above) | `llama3.1:8b` | Chat model; reasoning flavor via `LLM_REASONING_MODEL`. |
| `LLM_MOCK_RESPONSE` | `app/llm/adapter.py` (superseded, see note above) | `UNSURE` | Returned when `LLM_PROVIDER=mock`. |
| `LLM_TIMEOUT` | `app/llm/adapter.py` (superseded, see note above), `app/llm/embeddings.py` (superseded, see note above) | `120` s (chat); `60` s (embeddings) | HTTP timeouts for provider calls. |
| `OLLAMA_HOST` / `OLLAMA_URL` | `app/llm/adapter.py` (superseded, see note above), `app/llm/embeddings.py` (superseded, see note above) | `http://127.0.0.1:11434` | Base URL for Ollama chat + embeddings. |
| `OLLAMA_EMBED_MODEL` / `EMBED_MODEL` | `app/llm/embeddings.py` (superseded, see note above) | `nomic-embed-text:latest` | Embedding model for `/api/embeddings`. |
| `EMBED_DIM` | `app/embedding_config.py` | `1536` | Expected embedding dimension (identity). See `docs/EMBEDDINGS.md` for the normative 768-vs-1536 nuance. |
| `OPENAI_API_KEY`, `OPENAI_BASE` | `app/llm/adapter.py` (superseded, see note above) | – / OpenAI chat URL | Required when `LLM_PROVIDER=openai`. |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` | `app/llm/adapter.py` (superseded, see note above) | – / DeepSeek chat URL | Required when `LLM_PROVIDER=deepseek`. |
| `INDEX_OUTBOX_PATH` | watcher/cli (`app/outbox/events.py`, `app/index/outbox.py`) | `tmp/index-outbox.jsonl` | JSONL audit log (non-canonical); watcher may append for diagnostics. |
| `DATABASE_URL` / `DB_DSN` | `app/services/outbox.py`, runtime | (none) | DB connection string (required when DB outbox is enabled/required). |
| `STORE_BACKEND` | watcher/runtime (`app/watcher/registry.py`) | `memory` | Controls some watcher gating/requirements. |
| `PKM_SETTINGS_PROFILE` | settings tier gate (`app/settings/tiering.py`) | `operator` | Settings tier enforcement profile (`operator` default, `lab` for dev/lab-only knobs). |
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
| `acquire-replay RAW_RECORD_ID --vault-root PATH [--assert-no-source-egress --json --trace-id]` | app/cli/__init__.py:525-585 | Knowledge Acquisition (KA-06, #2801): replays an existing `knowledge_acquisition.raw` record's derived levels (normalize → extract → candidate) with a runtime-enforced zero-source-egress guard; prints the per-stage replay receipt. | 0 when the replay is equivalent; exit 1 (`ClickException` / non-equivalent receipt) otherwise. |
| `pipe SOURCE [--json --trace-id]` | app/cli/__init__.py:96-133 | Normalize → classify (+transcribe when audio/URL) and write aggregated JSONL audit log. | 0 on success, exit 1/2 on missing sources. |
| `health [--json --trace-id]` | app/cli/__init__.py:135-147, app/cli/health.py | Local dependency checks (ffmpeg, yt-dlp, INDEX_OUTBOX_PATH, Ollama reachability). | 0 when `ok=true`, otherwise 1. |

## Knowledge Acquisition (`app/knowledge_acquisition/`)
Phase 2 vertical slice (epic #2795, KA-01..KA-06): `youtube_url` source plugin `fetch()` →
`normalize()` → one schema-gated extractor → governed candidate `youtube_source_note` writeback,
replayable end-to-end from immutable raw evidence with outbox stage events. `fetch()` is a library
entry point, not a standalone CLI command in this slice; `acquire-replay` (above) is the one CLI
surface the package ships. Pipeline ends at an unreviewed candidate note — no triage advancement,
no indexing (deferred to epic #2314).

| Module | Role |
| --- | --- |
| `youtube_plugin.py` | `youtube_url` source plugin (KA-01/#2796, KA-02/#2797): caption-first fetch (manual track preferred, original-language-only), ASR fallback via `app/media/transcribe.py` when captionless. Persists an immutable `knowledge_acquisition.raw` record keyed on `(source_kind, item_ref, content_identity)`. |
| `raw_record.py` | Deterministic UUID5 `raw` record identity + persist/find/get against the canonical `app.objects` StorePort seam; dedup no-op on unchanged content. `emit_outbox=False` — the raw fetch is deliberately pre-pipeline. |
| `normalize.py` | KA-03/#2798: deterministic `raw` → `normalized` transcript stage — VTT cue parsing + rolling-cue dedup for caption methods, direct segment read for `asr`; fail-loud on a non-empty body that normalizes to zero segments. |
| `extraction_registry.py` | KA-04/#2799: open registry mapping an `extractor_id` to a schema-gated run function; `run_extractor` is the pipeline's one call site. |
| `extractors/summary_extractor.py` | The `summary` extractor (KA-04/#2799): one schema-gated LLM call over a `normalized` transcript via `app/components/llm/constrained.py`, routed per `docs/LLM_ROUTING.md`. |
| `candidate_writeback.py` | KA-05/#2800: candidate assembly (re-derives normalize + extraction in-process) + governed `youtube_source_note` companion-note write through `WriteGuard`, with mandated posture markers (`authority.requires_review: true`, `review_state: draft`). First-write-wins. |
| `replay.py` | KA-06/#2801: replays every derived level from an existing `raw` record with a runtime-enforced zero-source-egress guard (raises on any source-egress seam reached during replay); emits per-stage outbox events and returns a typed, per-stage-equivalence-classed receipt. Backs the `acquire-replay` CLI command. |
| `stage_events.py` | KA-06/#2801: stage-event emission (`knowledge_acquisition.stage.completed` / `.dead_lettered`) with deterministic idempotency keys; item-scoped extractor orchestration (`run_extractors`). |

## External tools and network calls
- **yt-dlp** – downloads audio / m4a (`app/media/transcribe.py:22-39`).
- **ffmpeg** – converts arbitrary formats to 16 kHz mono wav (`app/media/transcribe.py:47-65`).
- **faster-whisper** – local ASR with `_MODEL_CACHE` (`app/media/transcribe.py:68-99`).
- **Ollama** – `/api/chat` and `/api/embeddings` (`app/agents/qa/agent.py:31-48`, `app/llm/embeddings.py:34-43`).
- **httpx / requests** – also used for OpenAI/DeepSeek (`app/llm/adapter.py:16-47`, superseded — see Environment variables note above; canonical access is `app/components/llm/`).
- **yt-dlp (metadata + caption tracks)** – `app/knowledge_acquisition/youtube_plugin.py::yt_dlp_extract_info`; egress posture `youtube.com` + `googlevideo.com`, logged-out, low volume, politeness sleeps. The PO-token provider plugin (`bgutil-ytdlp-pot-provider`) is a declared local dependency for the subtitle endpoint's PO-token enforcement, wired via yt-dlp's extractor-args provider framework.

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
- `LLM_TIMEOUT` governs Ollama/OpenAI/DeepSeek HTTP calls (60–120 s). No automatic retry yet; see `docs/LLM.md`.
- `CircuitBreaker` and `timeout_wrapper` live in `app/quality/guardrails.py`; usage varies by subsystem.
- Span logging includes latency and status (`app/obs/log.py`), powering the `jq` recipes in `docs/OBSERVABILITY.md`.
<!-- SECTION:INVENTORY:END -->
