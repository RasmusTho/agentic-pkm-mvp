State: SoT v4.10 Reality-MVP (current).
# Glossary

Brief definitions for recurring concepts.

<!-- SECTION:GLOSSARY:BEGIN -->
- **Outbox** – Canonical DB outbox queue in runtime; JSONL (`INDEX_OUTBOX_PATH`) is the audit log (`app/events/outbox.py`, `app/index/outbox.py`).
- **Embedding** – Floating-point vector from `app/llm/embeddings.py` (Ollama `/api/embeddings` or mock) stored in-memory by `MemoryHybridStore`.
- **BM25** – Lexical scorer (`rank_bm25.BM25Okapi`) used in hybrid retrieval.
- **Rerank** – Planned cross-encoder stage that refines retrieval ordering (see `docs/ROADMAP.md`).
- **Span** – `@span("node")` decorator in `app/obs/log.py` logging latency + `trace_id`.
- **Guardrails** – Rules in `app/quality/guardrails.py` preventing forbidden content, enforcing sources, and capping tokens.
- **Circuit breaker** – `CircuitBreaker` in `app/quality/guardrails.py` limiting failures per time window.
- **Index outbox JSONL** – `{object_id, kind, source_ref, payload}` audit lines (see `docs/INVENTORY.md`).
- **Hybrid store** – In-memory combination of BM25 + embeddings + fuzzy overlap (`app/retrieval/hybrid.py`).
- **Health CLI** – `python -m app.cli health --json`, validates ffmpeg, yt-dlp, outbox path, and Ollama reachability.
<!-- SECTION:GLOSSARY:END -->
