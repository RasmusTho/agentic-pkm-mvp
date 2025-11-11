# Changelog

## v4.5A — Stable baseline
Date: 2025-11-11

Highlights:
- Deterministic CI in memory mode (no Postgres dependency).
- `audit_log()` graceful fallback to in-memory ring buffer with optional JSONL sink.
- LLM retry helper with bounded backoff for local Ollama calls; instant deterministic mock.
- Batch-friendly embeddings and hybrid retrieval build via `embed_batches`.
- Memory `VectorIndex` JSONL persistence (`INDEX_PERSIST_PATH`, gated load via `INDEX_PERSIST_LOAD`).
- Pluggable `RerankerProvider` with deterministic `mock_ce` and inert default.
- Optional rerank hook `apply_optional_rerank()` behind `RERANK_ENABLE` and `RERANK_TOP_K`.
- Docs synced: Architecture, Roadmap, Status, and Mermaid diagram exportability.
- CI: smoke workflow runs `pytest -q -m "not pg"` and seeds a persisted index file.

Upgrade notes:
- No schema changes. Memory-first remains default for CI.
- To enable rerank locally: set `RERANK_ENABLE=1` and `RERANK_PROVIDER=mock_ce`.
- Persist index during local runs by setting `INDEX_PERSIST_PATH=tmp/index.jsonl`.
