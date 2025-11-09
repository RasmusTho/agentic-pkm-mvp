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
