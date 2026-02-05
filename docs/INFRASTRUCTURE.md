State: SoT v5.5 baseline (descriptive, ops-oriented). If a detail drifts, prefer scripts/compose and update this doc.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Infrastructure — Local Runtime (Docker + Colima)

This document describes the current local runtime for the Agentic PKM stack. It mirrors the active docker-compose setup and the supporting scripts.

## Stack Overview
- Host: macOS
- Container runtime: Colima provides the Docker daemon.
- Orchestration: Docker Compose in repo root.
- Services: Postgres (pgvector), FastAPI API, Outbox worker. Redis/agent containers may exist as legacy/orphaned but are not required for the current flow.
- Vaults: Live on the host; the app reads them via configured paths (`DEFAULT_VAULT_ROOT` / `VAULT_ROOT`).

### Text Diagram
```
macOS host
  └── Colima (Docker runtime)
        └── docker compose (repo root)
              ├── db  (pgvector/pgvector:pg16)  [port 15432 -> 5432]
              ├── api (workspace-app image)     [port 18000 -> 8000]
              └── worker (workspace-app image)
```
API and worker share the same Python image built from the repo.

## Services
- **db**: `pgvector/pgvector:pg16`, credentials `app/app`, database `app`, exposed on `127.0.0.1:15432`.
- **api**: FastAPI app (`app.main:app`) listening on `8000` in-container, mapped to `18000` on the host.
- **worker**: Background outbox consumer (`app.workers.outbox_worker`) sharing the same image and code as the API.
- **redis/agent**: May be present as historical/orphaned containers; not required for the current Reality-MVP path.

## Environment & Configuration
- Database DSN: `DATABASE_URL` / `DB_DSN` (e.g. `postgresql+psycopg://app:app@db:5432/app`).
- Store backend: `STORE_BACKEND=pg` in containers (memory is used for fast tests/CI).
- LLM backends:
  - Containers: `LLM_PROVIDER=mock` for deterministic startup.
  - Host CLI (e.g. alpha ingest): typically `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=llama3.1:8b`, `OLLAMA_EMBED_MODEL=nomic-embed-text:latest`.
- Extensions: `pgcrypto` and `vector` ensured by startup scripts.
- Outbox: Backed by the `outbox` table in Postgres; worker polls it continuously. JSONL (`INDEX_OUTBOX_PATH`) remains audit-only.

## Startup Flow
1. Ensure Colima/Docker is running.
2. `docker compose up -d` builds the shared Python image and starts `db` → `api` → `worker`.
3. `scripts/start_api.sh` (container entrypoint):
   - Normalizes the DSN from `DATABASE_URL` / `DB_DSN`.
   - Waits for Postgres to accept connections.
   - Creates `vector` and `pgcrypto` extensions.
   - Runs Alembic migrations.
   - Launches Uvicorn on `0.0.0.0:8000`.
4. Worker bootstrap:
   - Uses an autocommit psycopg connection to create the `outbox` table/indexes and `pgcrypto` if needed.
   - Polls the outbox and triggers the indexer for ingest events.

## Observability
- Health endpoints: Reality-MVP operators should hit `http://127.0.0.1:18000/healthz` (liveness), `/readyz` (readiness), `/api/health` (structured contract), and `/api/status` (SOT/status payload). Search and ask live at `/search` and `/api/ask` on the same host port. Docker Compose maps host `18000` ↔ container `8000`, so use the host port when invoking curl from the host. The legacy `/agent/health` surface lives under `app.legacy_http`, but go-live checks should rely on `/healthz` (simple OK) and `/api/health` (contract) instead. `/api/health` can report `ok=false` when optional tools like `ffmpeg` are missing; treat this as degraded functionality if core endpoints are healthy.
- Route truth: Swagger UI at `/docs` and the OpenAPI JSON at `/openapi.json` describe every available path; consult `docs/runbooks/RUNBOOK_GO_LIVE.md` for command examples and the `curl -sS http://127.0.0.1:18000/openapi.json` tip from that runbook when you are unsure.
- Vault ingest: Compose mounts the vault under `/app/vault`; `scripts/start_full_system.sh` validates that mount, checks for Markdown notes, and only runs `vault-alpha-ingest` when `store stats` reports zero objects so the store starts from a deliberate batch ingest. Watchers/worker runs remain incremental and do not sweep the entire vault after the bootstrap job.
- Prometheus instrumentation is available via `prometheus-fastapi-instrumentator` (metrics exposure is gated by settings).

## Relation to Alpha Vault & Ingest
- Ingest/ASK flows talk to the same Postgres DSN used by compose (`127.0.0.1:15432`).
- Alpha ingest from the host typically runs with Ollama embeddings and `STORE_BACKEND=pg`, emitting DB outbox events consumed by the worker.

## Recovery: Re-index from Alpha vault
Use this when `/api/status` reports `vault` object_count = 0 and `vault-alpha-ingest` reports `ingested 0 notes` even though Concepts/Test contain content or mirrors.

Run from the host (venv active):
```
cd ~/workspace
source .venv/bin/activate

export STORE_BACKEND=pg
export DATABASE_URL=postgresql://app:app@127.0.0.1:15432/app

export LLM_PROVIDER=ollama
export OLLAMA_MODEL=llama3.1:8b
export OLLAMA_EMBED_MODEL=nomic-embed-text:latest

export INDEX_OUTBOX_PATH=/tmp/index-outbox-alpha-concepts.jsonl

python -m app.cli vault-alpha-ingest \
    --max-notes 200 \
    --include-test-note \
    --force
```
`INDEX_OUTBOX_PATH` is used for the JSONL audit log only; the worker consumes DB outbox rows. Ensure `docker compose up -d` (or `scripts/dev_bootstrap.sh`) is running so the worker processes new outbox events and re-indexes the vault.
