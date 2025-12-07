State: SoT v4.10 Reality-MVP (current).
# Glossary

Brief definitions for recurring concepts.

<!-- SECTION:GLOSSARY:BEGIN -->
- **Outbox** – JSONL file (`INDEX_OUTBOX_PATH`) where ingestion/transcribe events land before indexing (`app/index/outbox.py`).
- **Embedding** – Vector from `app/llm/embeddings.py` (Ollama/remote or mock) stored in ObjectStore + VectorIndex (and in-memory HybridStore).
- **BM25** – Lexical scorer (`rank_bm25.BM25Okapi`) used in hybrid retrieval.
- **Rerank** – Optional cross-encoder stage that reorders hybrid hits (`RERANK_ENABLE`, provider in settings); defaults off.
- **Span** – `@span("node")` decorator in `app/obs/log.py` logging latency + `trace_id`.
- **Guardrails** – Rules in `app/quality/guardrails.py` preventing forbidden content, enforcing sources, and capping tokens.
- **Circuit breaker** – `CircuitBreaker` in `app/quality/guardrails.py` limiting failures per time window.
- **Index outbox JSONL** – `{object_id, kind, source_ref, payload}` lines (see `docs/INVENTORY.md`).
- **Hybrid store** – In-memory combination of BM25 + embeddings (`app/retrieval/hybrid.py`); warmed from Store on first `/api/ask`.
- **Health CLI** – `python -m app.cli health --json`, validates ffmpeg, yt-dlp, outbox path, and Ollama reachability.
<!-- SECTION:GLOSSARY:END -->
