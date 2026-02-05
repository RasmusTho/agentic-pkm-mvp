State: SoT v5.5 baseline (descriptive). Definitions here should match the codebase; if you rename a concept in code, update this doc.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Glossary

Brief definitions for recurring concepts.

<!-- SECTION:GLOSSARY:BEGIN -->
- **Outbox** – Canonical DB outbox queue used by watcher/worker (`app/services/outbox.py`). JSONL (`INDEX_OUTBOX_PATH`) is a non-canonical audit log (`app/outbox/events.py`, `app/index/outbox.py`).
- **Embedding** – Floating-point vector from `app/llm/embeddings.py` (Ollama `/api/embeddings` or mock); used in retrieval/indexing.
- **BM25** – Lexical scorer (`rank_bm25.BM25Okapi`) used in hybrid retrieval.
- **Rerank** – Optional reordering stage in retrieval, enabled via `RERANK_ENABLE` and implemented under `app/retrieval/rerank/`.
- **Span** – `@span("node")` decorator in `app/obs/log.py` logging latency + `trace_id`.
- **Guardrails** – Rules in `app/quality/guardrails.py` preventing forbidden content, enforcing sources, and capping tokens.
- **Circuit breaker** – `CircuitBreaker` in `app/quality/guardrails.py` limiting failures per time window.
- **Index outbox JSONL** – `{object_id, kind, source_ref, payload}` audit lines (see `docs/INVENTORY.md`).
- **Hybrid store** – In-memory combination of BM25 + embeddings + fuzzy overlap (`app/retrieval/hybrid.py`).
- **Health CLI** – `python -m app.cli health --json` validates local deps (ffmpeg/yt-dlp), outbox settings, and LLM reachability.
<!-- SECTION:GLOSSARY:END -->
