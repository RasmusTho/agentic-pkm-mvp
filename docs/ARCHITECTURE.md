# Arkitektur (externa komponenter)

## Översikt

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

## Externa beroenden
- **Ollama** (LLM, lokalt)
- **faster-whisper** + **ffmpeg** + **yt-dlp** (ASR/Media)
- **BM25** (Whoosh/Elasticsearch-valfritt lokalt lib)
- **Embeddings** (lokal cache; provider-agnostisk)
- **Storage**: memory (MVP) -> Postgres (senare)

## Kontrakt
- **Index-outbox line (JSONL)**: `{object_id, kind, source_ref, payload{...}, embedding?, topic}`
- **Retrieve(query)** -> `[ {doc_id, snippet, score, source_ref} ]`
- **Agent I/O**: prompt med sektioner `{Instruktioner, Kontext, Fråga, Krav}`, svar med `Sammanfattning + Källor`.

## Kvalitet
- Hybrid RAG (BM25+Emb) + rerank, trösklar och self-check.
- Gardrails: assertions för scorers, tokenbudget och förbjudet innehåll.

<!-- SECTION:SYSTEM-MAP:BEGIN -->
## Levande karta (ingestion → index → retrieval → agent → guardrails → outbox)
1. **Ingestion/Normalize** – `app/agents/normalizer/agent.py` läser fil/URL, bygger core6-payload och sparar via `ObjectStore`. Trace-id propageras från CLI (`app/cli/__init__.py`).
2. **Classifier** – `app/agents/classifier/agent.py` hämtar objektet, kör `app/llm/adapter.generate` (styrt av `LLM_PROVIDER`/`LLM_MODEL`) och skriver beslut + memories.
3. **Transcribe (vid behov)** – `app/media/transcribe.py` triggas av CLI `pipe` eller `transcribe`. yt-dlp + ffmpeg producerar wav → faster-whisper → JSONL-post i `INDEX_OUTBOX_PATH`.
4. **Index outbox** – `app/index/outbox.py` appendar posten och försöker fan-in text till `app/retrieval/hybrid.get_store()` (BM25-tokenizer + embed-cache).
5. **Retrieval** – `app/retrieval/hybrid.hybrid_search` kombinerar BM25 + embeddings + tokenöverlapp. Embeddings hämtas via `app/llm/embeddings.py` mot Ollama `/api/embeddings`.
6. **QA-agent** – `app/agents/qa/agent.py` kör retrieval → draft → self-check → finalize med spans `agent.*`. LLM-anrop går via Ollama `/api/chat` (eller mock) och loggas med `trace_id`.
7. **Guardrails & quality** – `app/quality/guardrails.py` validerar förbjudet innehåll, källa och tokenbudget innan svar returneras.
8. **Outbox/outbound** – CLI `pipe` och transcribe skriver JSONL-händelser som indexer/outbox-worker kan konsumera vidare till långsiktigt index.

### Externa verktyg + env-koppling
- **yt-dlp / ffmpeg / faster-whisper** – kräver `TRANSCRIBE_CACHE_DIR`, `ASR_MODEL`, `ASR_DEVICE`.
- **Ollama** – `OLLAMA_HOST`/`OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`, `LLM_TIMEOUT`. Health-CLI verifierar `/api/tags`.
- **ObjectStore/DB** – `STORE_BACKEND`, `DATABASE_URL`, `MEMORY_ENABLED`.
- **Outbox/Index** – `INDEX_OUTBOX_PATH` måste vara skrivbar; CLI pipeline skriver markörer `kind=pipeline`.

### Systemgränser
- **Ingestion** accepterar Markdown/URL via CLI eller API (se `docs/CLI.md`). Tester körs med `LLM_PROVIDER=mock`.
- **Index** består av JSONL + in-memory hybridstore. Persistens till Postgres ligger på `docs/ROADMAP.md` (cross-encoder rerank + index-persistens).
- **Retrieval/Agent** använder endast JSONL + embed-cache; inga externa tjänster utöver LLM.
- **Guardrails** är rena Python-funktioner men planeras att kompletteras med retry/circuit-breakers (gap i `docs/QUALITY.md`).
<!-- SECTION:SYSTEM-MAP:END -->
