State: SoT v4.10 Reality-MVP (current).
# SETTINGS

Runtime/env configuration is simple in Reality-MVP: defaults favor local development (memory stores, mock LLM). For topology and ports see `docs/SYSTEM_DESIGN_v4.10.md`.

## Core env vars
- `STORE_BACKEND` — `memory` (default) or `pg`. When `pg`, set `DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:15432/app`.
- `INDEX_OUTBOX_PATH` — JSONL outbox path (default `tmp/index-outbox.jsonl`).
- `METRICS_ENABLED` — `1` to expose Prometheus metrics on `/metrics` (disabled by default).
- `LLM_PROVIDER` — `mock` (default for CI/smoke), `ollama`, `openai`, `deepseek`. Chat/QA defaults are derived from this.
- `LLM_MODEL` — chat/QA model id (e.g., `llama3.1:8b` for Ollama).
- `EMBED_MODEL` — embedding model id (e.g., `nomic-embed-text` for Ollama); deterministic hash embedding is used in tests.
- `RERANK_ENABLE` / `RERANK_PROVIDER` — optional rerank; defaults keep rerank off in smoke/CI.
- `METRICS_ENABLED`, `OBSERVABILITY_OTLP_ENDPOINT` — enable metrics/traces (optional; see `docs/OBSERVABILITY_STACK.md`).

## CLI/health helpers
- `LLM_MOCK_RESPONSE` — text/JSON returned when `LLM_PROVIDER=mock`.
- `INGEST_STATUS_PATH` — where ingest status JSON is written during CLI flows (defaults under `tmp/`).
- `PLANNER_ENABLE` / `ORCHESTRATOR_ENABLE` / `A2A_ENABLE` / `MCP_ENABLE` — feature flags; default off for smoke runs. CLI `ask` enables orchestrator flow regardless of these flags for the demo pipeline.

## Conventions
- Services read env first, then fall back to defaults in settings bundles (`app/settings/*`) or agent modules.
- Keep secrets out of the repo; `.env` is for local dev only. Use the same env variables for Compose and bare-metal runs.
