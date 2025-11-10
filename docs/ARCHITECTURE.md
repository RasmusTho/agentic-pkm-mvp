# Architecture (external components)

## Overview

[Clients] -> [HTTP/CLI Ingest] -> [Normalizer] -> [Index Outbox]
|                |
[Transcriber]         v
|         [Indexer/RAG] -> [Reranker]
v                |
[Transcript JSON]      v
(segments+lang)       [Agent Loop]
|
[Guardrails]
|
[Response]

## External dependencies
- **Ollama** (local LLM backend)
- **faster-whisper** + **ffmpeg** + **yt-dlp** (ASR / media tooling)
- **BM25** (memory-only implementation, compatible with future Whoosh/Elasticsearch backends)
- **Embeddings** (local cache; provider-agnostic)
- **Storage**: in-memory (MVP) with a path toward Postgres

## Contracts
- **Index-outbox line (JSONL)**: `{object_id, kind, source_ref, payload{...}, embedding?, topic}`
- **Retrieve(query)** -> `[ {doc_id, snippet, score, source_ref} ]`
- **Agent I/O**: prompt sections `{Instructions, Context, Question, Requirements}`, answer with `Summary + Sources`.

## Quality controls
- Hybrid RAG (BM25 + embeddings) with rerank, thresholds, and self-check.
- Guardrails: assertions for scorers, token budgets, and forbidden content.

<!-- SECTION:SYSTEM-MAP:BEGIN -->
## Living map (ingestion → index → retrieval → agent → guardrails → outbox)
1. **Ingestion/normalize** – `app/agents/normalizer/agent.py` ingests files/URLs, builds the core6 payload, and stores through `ObjectStore`. Trace IDs propagate from the CLI (`app/cli/__init__.py`).
2. **Classifier** – `app/agents/classifier/agent.py` fetches the object, executes `app/llm/adapter.generate` (regulated by `LLM_PROVIDER` / `LLM_MODEL`), and writes decisions + memories.
3. **Transcribe (optional)** – `app/media/transcribe.py` runs via CLI `pipe` or `transcribe`. yt-dlp + ffmpeg emit wav → faster-whisper → JSONL entries under `INDEX_OUTBOX_PATH`.
4. **Index outbox** – `app/index/outbox.py` appends the entry and attempts to fan text into `app/retrieval/hybrid.get_store()` (BM25 tokenization + embedding cache).
5. **Retrieval** – `app/retrieval/hybrid.hybrid_search` blends BM25, embeddings, and token overlap. Embeddings come from `app/llm/embeddings.py` through Ollama `/api/embeddings`.
6. **QA agent** – `app/agents/qa/agent.py` executes retrieval → draft → self-check → finalize with `@span("agent.*")`. LLM calls go through Ollama `/api/chat` (or mock) and log the `trace_id`.
7. **Guardrails & quality** – `app/quality/guardrails.py` enforces forbidden-pattern, source-count, and token-budget rules before returning the answer.
8. **Outbox/outbound** – CLI `pipe` and transcribe commands write JSONL events that down-stream indexers/outbox workers consume for persistent indexing.

### External tools + env bindings
- **yt-dlp / ffmpeg / faster-whisper** – require `TRANSCRIBE_CACHE_DIR`, `ASR_MODEL`, `ASR_DEVICE`.
- **Ollama** – `OLLAMA_HOST` / `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`, `LLM_TIMEOUT`. The health CLI checks `/api/tags`.
- **ObjectStore / DB** – `STORE_BACKEND`, `DATABASE_URL`, `MEMORY_ENABLED`.
- **Outbox / index** – `INDEX_OUTBOX_PATH` must be writable; CLI pipelines emit `kind=pipeline` markers.

### System boundaries
- **Ingestion** accepts Markdown/URLs via CLI or API (see `docs/CLI.md`). Tests default to `LLM_PROVIDER=mock`.
- **Index** is JSONL + in-memory hybrid store today; persistence to Postgres is tracked in `docs/ROADMAP.md` (cross-encoder rerank + index persistence).
- **Retrieval / agent** only relies on JSONL + the embedding cache; no external services beyond the LLM provider.
- **Guardrails** are plain Python logic for now; retries/circuit breakers are called out as a gap in `docs/QUALITY.md`.
<!-- SECTION:SYSTEM-MAP:END -->
