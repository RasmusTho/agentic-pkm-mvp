State: SoT v4.10 Reality-MVP (current core).
# Runtime Inventory

Single source of truth for runtime knobs and surfaces. Defaults favor local/mock; Ollama or remote providers are opt-in.

<!-- SECTION:INVENTORY:BEGIN -->
## Environment (key vars)
- `STORE_BACKEND` — `memory` (default for CI/smoke) or `pg`. With `pg`, set `DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:15432/app`.
- `INDEX_OUTBOX_PATH` — JSONL outbox path (default `tmp/index-outbox.jsonl`); must be writable (health checks it).
- `LLM_PROVIDER` — `mock` (CI/smoke default), `ollama` (local), `openai`, `deepseek`.
- `LLM_MODEL` — chat/QA model id (e.g., `llama3.1:8b` for Ollama); `LLM_REASONING_MODEL` for reasoning calls.
- `EMBED_MODEL` / `OLLAMA_EMBED_MODEL` — embedding model id (default `nomic-embed-text`).
- `LLM_TIMEOUT` — chat timeout (120 s chat, ~60 s embeddings/other HTTP); no automatic retries.
- `METRICS_ENABLED` — `1` to expose `/metrics` (Prometheus).
- `RERANK_ENABLE` / `RERANK_PROVIDER` — optional rerank (`none|mock|ce_local|ce_http`); defaults off.
- `ASR_MODEL` / `ASR_DEVICE` — faster-whisper model/device (`base`/`auto` defaults).
- `INGEST_STATUS_PATH` — ingest status JSON for CLI flows (default under `tmp/`).

## CLI (Click, `python -m app.cli ...`)
- `vault-alpha-ingest` / `ingest-vault-root` / `pkm-alpha-ingest` — vault ingest (UUID healing, mirror write, panel stripping).
- `ask` — planner/orchestrator ASK pipeline (mock LLM default).
- `alpha-human-flows` — demo/regression flow A–F.
- `normalize` / `classify` / `transcribe` / `pipe` — legacy single-shot helpers.
- `health` — checks ffmpeg, yt-dlp, `INDEX_OUTBOX_PATH`, Ollama (when enabled).

## Retrieval/ASK
- HybridStore combines BM25 + embeddings; warmed from Store on first `/api/ask`.
- Rerank optional (env/settings). ASK returns sources with `origin`/`path` when present in payload.

## Logs, spans, and outbox
- JSON span logging via `@span` (latency + status) powers `docs/OBSERVABILITY.md` recipes.
- Outbox JSONL entries: `{object_id, kind, source_ref, payload, embedding?, trace_id?}` (see `app/index/outbox.py`); health writes a test record to validate permissions.

## Edge cases
- yt-dlp/ffmpeg missing → health fails and `transcribe` exits non-zero.
- Ollama offline → ASK/QA fall back to mock only if configured; otherwise HTTP errors surface.
- Unwritable outbox path → health fails; CLI writes raise.
<!-- SECTION:INVENTORY:END -->
