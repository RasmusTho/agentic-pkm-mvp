# Changelog

## v4.6 — Retrieval Quality & Reasoning Prep (in progress)
- Cross-encoder providers (`ce_local`, `ce_http`) behind `RERANK_ENABLE`, with graceful fallback to `mock_ce`; golden-set evaluation compares ce_local vs baseline and CI prints `EVAL P@10` / `nDCG@10`.
- RelationIndex v1 gains `has_any()` plus the Promotion orphan gate (default block) with audited overrides via `PROMOTION_ALLOW_ORPHANS` + `PROMOTION_ORPHAN_OVERRIDE_REASON`; CI reports relation coverage.
- Diarization hook wired into transcription with providers (`none|mock|external`) behind `DIARIZE_ENABLE`, feeding speaker-aware chunking.
- Golden set evaluation pipeline (`data/golden/*`) produces Precision@k and nDCG@k metrics in CI; doc integrity + PR/issue templates keep contracts enforced.

## v4.5B — Fitness & Hook Readiness
- QAS-003/QAS-010 latency checks implemented in `app.fitness.metrics` and executed via GitHub smoke workflow.
- Hybrid rerank hook integration completed with adapter and provider matrix.
- Chunking + dedup pipeline codified with deterministic chunk policy and shared deduper helpers.
- Docs/STATUS updated with CI measurement notes; ROADMAP reflects delivered P1 (rerank) + P2 (chunk/dedup).

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
