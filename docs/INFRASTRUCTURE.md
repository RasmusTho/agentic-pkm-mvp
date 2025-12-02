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
- Outbox: Backed by the `outbox` table in Postgres; worker polls it continuously.

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
- Health endpoints: `/agent/health` (legacy agent surface) and `/api/status` (Reality-MVP status) on port `18000`.
- Prometheus instrumentation is available via `prometheus-fastapi-instrumentator` (metrics exposure is gated by settings).

## Relation to Alpha Vault & Ingest
- Ingest/ASK flows talk to the same Postgres DSN used by compose (`127.0.0.1:15432`).
- Alpha ingest from the host typically runs with Ollama embeddings and `STORE_BACKEND=pg`, emitting outbox events consumed by the worker.

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
Ensure `docker compose up -d` (or `scripts/dev_bootstrap.sh`) is running so the worker consumes new outbox events and re-indexes the vault.
