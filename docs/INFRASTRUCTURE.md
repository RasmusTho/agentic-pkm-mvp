State: SoT v5.5 baseline (descriptive, ops-oriented). Local Compose is the fallback runtime; the live
product topology is the new Linux/Tailscale host split recorded below. If a detail drifts, prefer live
host evidence and the deployment contract, then update this doc.

Documentation hierarchy: `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md` owns the
target operational-platform boundary. This document owns the local Docker/Colima fallback description
and records the verified live host boundary; it does not claim that the new-host deployment handoff is
already a separately delivered implementation.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Infrastructure — Local Fallback and New-Host Runtime

This document describes the local Docker + Colima fallback and the current live host boundary for the
Agentic PKM stack. It does not claim that local Compose is the live product deployment.

## Current live host boundary (verified 2026-08-22)

- Mac mini: Ollama/model serving only; no product API, worker, watcher, database, or Companion UI.
- `ygg-dev`: Linux/Tailscale dev runtime, API `:18001`, Companion UI `:8111`; reachable but degraded.
- `ygg-test`: intended isolated test runtime; no reachable host or endpoint was found.
- `ygg-prod`: Linux/Tailscale prod runtime, API `:18000`; liveness responds but functional health is
  failing and Companion UI `:8113` is unavailable.
- Both live APIs report `git_sha=unknown`; promotion cannot use them as immutable artifact evidence.

The repository still documents and supports local Compose commands for fallback development and
verification. Those commands do not deploy the new hosts and are not promotion evidence.

## Local fallback stack overview
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

## Cross-container vault and scalar-rollback contract

The full-host-vault overlay binds the selected host vault read-only into
`instance-state-init`, `api`, `worker`, and `watcher`. The init container must
see the same selected root as the runtime consumers so deployment admission can
validate drained legacy-owner roots from inside its container namespace.

The scalar-rollback overlay also exposes the repo-owned policy sources
read-only to `instance-state-init` at:

- `/run/scalar-rollback-policy/docker-compose.yaml`
- `/run/scalar-rollback-policy/docker-compose.scalar-rollback.yml`
- `/run/scalar-rollback-policy/nginx.conf`

The rollback guard fails closed unless that init service and all three policy
mounts are present. The ownership ledger keeps the selected vault's primary
identity inode-bound, while parent-chain identities are canonical-path-bound so
the same vault remains verifiable across container bind mounts. Nested-root
collision checks still compare authenticated sealed roots by resolved path when
their persisted parent identities cannot be compared directly.

### Scratch/rebootstrap boundary

The path-bound parent-chain identity is persisted under ledger schema v2. A
schema-v1 ownership ledger is not migrated or silently interpreted under the
new identity semantics; established v1 state fails closed with an explicit
`scratch/rebootstrap reset` error. Rebootstrap is an operator-controlled
replacement of the host-global ownership state after the external backup,
writer-drain, and deployment-quiescence proofs are complete. This repository
change does not perform that destructive reset.

## Feasibility: capacity-managed dev/test runtime

**Status:** Advisory feasibility snapshot, 2026-08-17. This section describes a
possible infrastructure posture; it does not change the current `dev` / `test` /
`prod` channel contracts or claim that a resource allocator is shipped.

### Decision summary

The proposed model is feasible for the current single-host Docker + Colima
topology:

- `prod` remains outside the resource pool and is never stopped by local
  development/test scheduling.
- `dev` and `test` remain distinct channels with distinct data, configuration,
  ports, and runtime-artifact paths.
- A non-production runtime slot may be allocated exclusively to `dev` or `test`.
  The default allocation is `dev`; a test run first stops the `dev` runtime and
  restores it after verification.
- If future host-capacity evidence permits it, an allocator may grant `dev`
  and `test` simultaneous runtime leases. Parallelism is an optimization, not a
  channel or isolation requirement.

This means that `test` does not need permanently reserved CPU, memory, ports, or
containers. The test *contract* remains available on demand even when the test
runtime is stopped.

### Evidence for feasibility

| Concern | Existing evidence | Feasibility result |
| --- | --- | --- |
| Channel identity | Compose projects are explicitly named `pkm-dev`, `pkm-test`, and `pkm-prod`; the Makefile provides channel-specific start/down targets (`Makefile :: COMPOSE_*`, `dev-down`, `test-down`, `dev-start-full`, `test-start-full`). | **Feasible.** The runtime can be stopped and started by channel without changing channel identity. |
| Port separation | Dev uses Postgres/API ports `15433`/`18001`; test uses `15434`/`18002`; prod uses `15432`/`18000` ([ENVIRONMENTS.md](ENVIRONMENTS.md#parallel-local-stacks)). | **Feasible.** Exclusive mode needs no new port allocation; parallel mode already has fixed port separation. |
| Persistent state | Dev and test use separate Postgres identities and runtime paths: `app_dev`/`tmp-dev` and `app_test`/`tmp-test` ([ENVIRONMENTS.md](ENVIRONMENTS.md#stores-and-persistence), [RELEASE_CHANNELS](RELEASE_CHANNELS/README.md#channel-model)). The `dev-down` and `test-down` targets do not remove named volumes. | **Feasible with guardrails.** Stopping containers must not be combined with volume deletion or reset unless the test workflow explicitly requests it. |
| Clean verification | `make test-start-full VAULT_ROOT=<path>` is the explicit test startup path, while `make bootstrap-test-channel` owns the idempotent test bootstrap (`Makefile :: test-start-full`, `Makefile :: bootstrap-test-channel`). | **Feasible.** Test can be a cold-start verification mode rather than an always-on service. |
| Code identity | The deployment model distinguishes the running channel from the candidate code ref; exact-SHA test UAT may use an isolated worktree or pinned image ([DEPLOYMENT_AND_ENVIRONMENTS.md](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#build-once--promote-model)). | **Conditional.** The allocator must never switch a dirty development checkout into test verification. Test needs a clean candidate checkout or image. |
| Mutual exclusion | Existing deployment and instance-state paths already use host-global leases and restart fences for mutation/recreate operations ([DEPLOYMENT_AND_ENVIRONMENTS.md](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#current-reality)). | **Partial.** These protect deployment/state transitions; they are not yet a general dev/test runtime-slot allocator. |
| Capacity decision | The repo has startup disk-space checks, but this study found no canonical CPU/memory budget or admission receipt for deciding whether `dev` and `test` may run concurrently. | **Open.** Dynamic parallelism requires measurement and an explicit admission rule before it should be enabled. |

### Recommended operating shape

Use a two-level policy:

1. **Safe default — exclusive non-prod slot.** `dev` owns the slot. A bounded
   test run acquires the slot, verifies that `dev` is stopped, starts the test
   channel with its explicit bindings, records the result, stops test, and
   restores dev. This is the minimum viable shape and does not require a new
   capacity model.
2. **Optional optimization — capacity-aware parallelism.** A future allocator
   may keep both channels active only after a read-only capacity check proves
   the host margin and obtains a short-lived `dev`/`test` runtime lease. A failed
   or unavailable capacity check falls back to exclusive mode; it must not
   silently start a second stack.

The resource allocator should own only runtime admission and lifecycle
coordination. It must not choose vaults, promotion refs, migration policy, or
release authority. Those remain owned by the environment, release-channel, and
deployment contracts.

### Required safety invariants for a future allocator

- `prod` is never a candidate for automatic stop, restart, or resource
  reclamation.
- A `test` start fails closed unless the effective `PKM_ENVIRONMENT`, DB DSN,
  vault binding, runtime-artifact path, Compose project, and candidate code
  identity all resolve to test.
- Stopping a runtime releases containers and ports but preserves its channel
  data volumes and operator-configured vaults.
- A test run uses a clean candidate checkout or immutable image; it does not
  use uncommitted dev worktree state as release evidence.
- Switching back to dev proves the dev project is healthy and that no test
  runtime remains bound to dev ports, volumes, vault paths, or runtime-env
  files.
- A crash or interrupted switch leaves an observable terminal state and a
  recoverable previous allocation; it must not report success merely because
  `docker compose down` returned zero.

### Feasibility conclusion and next evidence

The infrastructure does not need permanent test capacity to retain test's
verification value. The lowest-risk next shape is therefore **exclusive,
on-demand test execution with persistent channel state**, followed by a measured
capacity-admission experiment if parallelism remains valuable.

Before enabling dynamic parallelism, collect host-local evidence for cold-start
time, peak and steady-state CPU/memory, disk growth during image/build/start,
and the recovery time from an interrupted switch. The result should be a
versioned capacity receipt, not an operator intuition or a fixed hardware
assumption. Until that receipt and a runtime-slot lease exist, treat parallel
`dev` + `test` as supported by Compose topology but not as an admitted capacity
policy.

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
2. `make start` is the supported local startup path. It writes `tmp/runtime.env` for the default/prod local stack, brings up the core services, auto-selects a Docker-reachable Ollama endpoint when needed, and verifies the live runtime from inside the `api` container before exiting `0`. The `pkm-test` Compose/bootstrap lane writes `tmp-test/runtime.env` instead.
3. `docker compose up -d` remains available for low-level debugging, but it skips the startup wrapper's endpoint repair, vault probes, and authoritative runtime verification.
3. `scripts/start_api.sh` (container entrypoint):
   - Normalizes the DSN from `DATABASE_URL` / `DB_DSN`.
   - Waits for Postgres to accept connections.
   - Creates `vector` and `pgcrypto` extensions.
   - Runs Alembic migrations.
   - Launches Uvicorn on `0.0.0.0:8000`.
4. Worker bootstrap:
   - Uses an autocommit psycopg connection to create the `outbox` table/indexes and `pgcrypto` if needed.
   - Polls the outbox and triggers the indexer for ingest events.

### Runtime verification
- `make verify-runtime` is the recommended operator check once the stack is up.
- It verifies:
  - `docker compose ps`
  - container health for `db`, `api`, `watcher`, and `worker` when present
  - `docker compose exec -T api python -m app.cli health --json`
  - `docker compose exec -T api python -m app.cli status`
- The check exits non-zero when required runtime health is not green, even if optional health checks still report warnings.

### Ollama endpoint selection
- For `LLM_PROVIDER=ollama`, startup now probes candidate endpoints from inside the containerized runtime and persists the working endpoint into the active runtime env file (`tmp/runtime.env` by default, `tmp-test/runtime.env` for `pkm-test`).
- Candidate order:
  - configured endpoint
  - `DOCKER_OLLAMA_BASE_URL` when set
  - `http://host.docker.internal:11434`
  - `http://ollama:11434`
- This reduces drift between host-only Ollama URLs and what containers can actually reach.

### Colima / Docker recovery

If `docker ps`, `docker version`, `docker compose`, or `colima status` hang during startup, treat it
as a host-runtime problem before debugging app code. First free host disk if it is low, because Docker
builds and Colima SSH forwards can wedge under disk pressure. Then use the channel-safe sequence in
`docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`:

- inspect dev/prod ports from the host before restarting Colima;
- kill only clearly stuck client/wrapper processes when possible;
- try `colima stop default && colima start default`;
- use `LIMA_HOME="$HOME/.colima/_lima" limactl stop -f colima` only when the VM is running but
  Colima SSH resets or graceful stop hangs;
- restart only the intended channel target after recovery, for example `make dev-start-full` for
  `pkm-dev`.

## Observability
- Health endpoints: Reality-MVP operators should hit `http://127.0.0.1:18000/healthz` (liveness), `/readyz` (readiness), `/api/health` (structured contract), and `/api/status` (SOT/status payload). Search and ask live at `/search` and `/api/ask` on the same host port. Docker Compose maps host `18000` ↔ container `8000`, so use the host port when invoking curl from the host. The `/agent/health` compatibility route should not be used for go-live checks; rely on `/healthz` (simple OK) and `/api/health` (contract) instead. `/api/health` can report `ok=false` when optional tools like `ffmpeg` are missing; treat this as degraded functionality if core endpoints are healthy.
- Route truth: Swagger UI at `/docs` and the OpenAPI JSON at `/openapi.json` describe every available path; consult `docs/runbooks/RUNBOOK_GO_LIVE.md` for command examples and the `curl -sS http://127.0.0.1:18000/openapi.json` tip from that runbook when you are unsure.
- Vault ingest: Compose mounts the vault under `/app/vault`; `scripts/start_full_system.sh` validates that mount, checks for Markdown notes, and only runs `vault-alpha-ingest` when `store stats` reports zero objects so the store starts from a deliberate batch ingest. Watchers/worker runs remain incremental and do not sweep the entire vault after the bootstrap job.
- Prometheus instrumentation is available via `prometheus-fastapi-instrumentator` (metrics exposure is gated by settings).

## Local Observability Stack

This repo already emits structured logs and exposes Prometheus metrics when `METRICS_ENABLED=1`. Use the optional local stack when you want a developer/operator view of those signals.

Prerequisites:
- Docker engine running locally
- API server available on port `18000` with `METRICS_ENABLED=1`

```bash
export METRICS_ENABLED=1
uvicorn app.main:app --reload --port 18000
```

Optional worker metrics: the outbox worker exposes a Prometheus `/metrics` endpoint (via `prometheus_client`) only when `WORKER_METRICS_PORT` is set to a valid TCP port from `1` through `65535`; it stays off by default. The Prometheus scrape config expects port `9101`:

```bash
WORKER_METRICS_PORT=9101 python -m app.workers.outbox_worker
```

The main compose file passes `WORKER_METRICS_PORT` through to the `worker` service (default empty = off); scraping a containerized worker additionally requires publishing that port from the container, so the host-run worker above is the simple path.

Start Prometheus + Alertmanager + Grafana:

```bash
docker compose -f ops/observability/docker-compose.yaml up
```

- Prometheus UI: `http://localhost:9090`
- Alertmanager UI: `http://localhost:9093`
- Grafana UI: `http://localhost:3000`

Grafana should use Prometheus at `http://prometheus:9090` as a data source.

Alerting: `ops/observability/alerts.yml` ships basic rules (always-on scrape target down for 5m, API 5xx rate > 5% over 15m from the instrumentator's `http_requests_total`, worker poll loop stalled via `pkm_worker_last_tick_timestamp_seconds`). The opt-in worker target is deliberately excluded from the generic down rule — it would otherwise fire a permanent false critical while `WORKER_METRICS_PORT` is unset (the default) — and is instead covered by `WorkerMetricsDown`, which only fires once the worker `/metrics` endpoint has been seen up within the last hour and then become unreachable. Alertmanager runs with a log/UI-only null receiver — no external notification channels.

When finished:

```bash
docker compose -f ops/observability/docker-compose.yaml down
```

Typical local signal coverage:
- Capture & ingest throughput/errors
- ASK latency/volume
- Promotion/review event activity
- Panel intent activity
- Eval traces/logs when running locally

For quick log inspection without the stack:

```bash
uvicorn app.main:app --reload | jq
```

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
