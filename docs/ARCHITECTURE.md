# Architecture (SoT v4.5)

## Overview
The agentisk PKM stack ingests heterogeneous sources, normalizes them into canonical objects, and routes them through stores that stay consistent whether we run in Postgres or memory mode. Agents communicate through JSONL outbox events, making the system deterministic and replayable for CI and production. Every hop is observable via trace IDs and audit spans so that we can explain how content moved from the CLI to published knowledge.

## Store abstraction
`STORE_BACKEND` selects the provider, but agents program against three logical contracts:

- **ObjectStore** – owns canonical objects (notes, transcripts, media metadata). It handles UUID assignment, optimistic updates, and `emit_outbox=True|False` flags to control downstream fan-out. Memory adapters keep the same semantics for CI.
- **VectorIndex** – receives chunked text/audio views from the Outbox and maintains embeddings plus BM25 features. Retrieval always goes through `hybrid_search` so ranking logic stays centralized.
- **RelationIndex** – represents provenance, promotion history, speakers/entities, and other graph edges. Promotion Agent updates relations whenever the human-facing vault changes state.

These interfaces make the agents portable: no direct `psycopg` imports outside the providers, and swapping backends requires no agent rewrites.

## Outbox pattern
All state transitions emit JSONL entries to the Outbox. Writers declare a `topic` (`index.object.embedded`, `promote.intent.created`, etc.) and include `trace_id` + payload. Consumers poll via `app/index/outbox.py` APIs, which decode and ack entries atomically. Because Outbox lives on disk (memory backends write to a temp file) the entire ingestion → promotion loop can be replayed deterministically, which is how CI stays green without Postgres.

## Promotion Agent
`app/agents/promotion/agent.py` listens for `promote.intent.created` events, validates cooldowns, edits Markdown frontmatter ("frontmatter = Core-6" guard), and emits `promote.done` plus provenance edges. It always goes through ObjectStore with `emit_outbox=False` to avoid loops, then pushes a fresh outbox entry for downstream re-indexing. CI mode uses the same workflow with the mock LLM provider, ensuring SoT v4.5 stays testable without remote dependencies.

## External dependencies
- **Ollama** (local LLM + embeddings, optional when `LLM_PROVIDER=mock`).
- **faster-whisper**, **ffmpeg**, **yt-dlp** (audio / AV normalization).
- **BM25 + embeddings cache** (pure Python implementation backed by VectorIndex adapter).
- **Storage providers**: in-memory baseline, Postgres via psycopg when `STORE_BACKEND=pg`.

## Contracts
- **Index-outbox line (JSONL)**: `{object_id, kind, topic, source_ref, payload{...}, embedding?, trace_id}`.
- **Store APIs**: `ObjectStore.save_object`, `VectorIndex.upsert_chunks`, `RelationIndex.add_edge` always return truthy results and raise typed errors on conflicts.
- **Agent I/O**: prompt sections `{Instructions, Context, Question, Requirements}`, answers emit `Summary + Sources`.
- **Promotion workflow**: `intent.created` → validation → vault mutation → `promote.done` → `index.object.embedded`.

## Quality controls
- Hybrid RAG (BM25 + embeddings + rerank) with self-check and guardrails.
- Deterministic CLI and CI pathways: all commands accept `--trace-id` and log audit JSONL lines even in memory mode.
- Guardrails enforce token budgets, citation counts, and forbidden content filters before answers ship.

<!-- SECTION:SYSTEM-MAP:BEGIN -->
## Living map (ingestion → store → outbox → retrieval → promotion)
1. **Ingestion/normalize** – `app/agents/normalizer/agent.py` ingests files/URLs, builds the Core-6 payload, and persists via `ObjectStore.save_object(emit_outbox=True)` so downstream workers see the change.
2. **Classifier** – `app/agents/classifier/agent.py` fetches from ObjectStore, runs `app.llm.adapter.generate` (mockable), and writes memories + guardrail signals. Classifier tests can be skipped with `SKIP_CLASSIFIER_TESTS=1` for smoke runs.
3. **Transcribe (optional)** – `app/media/transcribe.py` plus yt-dlp/ffmpeg/faster-whisper emit JSONL segments under `INDEX_OUTBOX_PATH`, tagged with `trace_id` and source metadata.
4. **Index outbox** – `app/index/outbox.py` appends events and coordinates fan-in into VectorIndex + RelationIndex. The same helpers work for disk JSONL and Postgres-backed queues.
5. **Retrieval** – `app/retrieval/hybrid.hybrid_search` fuses BM25, embeddings, and optional cross-encoder rerank. Embeddings live in the cache under VectorIndex, ensuring zero Postgres requirement for QA agents.
6. **QA agent** – `app/agents/qa/agent.py` orchestrates retrieval → draft → self-check, recording spans via `audit_log`. Memory mode keeps JSONL audit buffers so traces remain inspectable.
7. **Guardrails & quality** – `app/quality/guardrails.py` enforces forbidden-pattern, source-count, and token-budget rules before returning the answer to CLI/API clients.
8. **Promotion & publishing** – Promotion Agent consumes intents, updates ObjectStore, emits `promote.done`, and reuses the Outbox to trigger re-index. RelationIndex edges capture provenance for future reasoning layers.
<!-- SECTION:SYSTEM-MAP:END -->

### External tools + env bindings
- **Media stack** – `TRANSCRIBE_CACHE_DIR`, `ASR_MODEL`, `ASR_DEVICE` gate faster-whisper + ffmpeg usage.
- **LLM/Ollama** – `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`, `LLM_TIMEOUT`. Health CLI probes `/api/tags` unless `LLM_PROVIDER=mock`.
- **Stores** – `STORE_BACKEND`, `DATABASE_URL`, `INDEX_OUTBOX_PATH`, `MEMORY_ENABLED` govern provider selection.
- **Outbox/Index** – Writers must guarantee the path exists; CLI helpers create directories in-memory for tests.

### System boundaries
- **Ingestion** accepts Markdown/URLs via CLI or API; tests default to `LLM_PROVIDER=mock` and memory stores.
- **Indices** stay JSONL + in-memory for SoT v4.5, with Postgres adapters available but optional.
- **Retrieval / Agent** depend only on stores + LLM provider; no direct Postgres coupling.
- **Guardrails** remain pure Python; retries/circuit breakers tracked separately in `docs/QUALITY.md`.
