State: SoT v5.5 Reality-MVP baseline locked. This is the top-level operations entrypoint for the current runtime.
Doc role: Core SoT
Authority: Top-level operator guidance for the current runtime; delegates specialized operational detail to linked companion docs but remains the main operational entrypoint.
# Operations Playbook

Use this document as the operator-facing starting point for runtime operations.

Specialized companion documents:
- `docs/HEALTH.md` - health CLI behavior and runtime health contract
- `docs/OBSERVABILITY.md` - runtime observability signals, counters, and span/log contracts
- `docs/INFRASTRUCTURE.md` - local runtime stack, Docker/Colima setup, and local observability stack

Reading order:
1. Start here for runtime expectations and runbooks.
2. Follow `docs/HEALTH.md` when verifying readiness or diagnosing degraded state.
3. Follow `docs/OBSERVABILITY.md` for interpreting telemetry and counters.
4. Use `docs/INFRASTRUCTURE.md` when you need Docker/runtime topology or the local monitoring stack.

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Runtime prerequisites (registry watcher)
- `DATABASE_URL` or `DB_DSN` is required in runtime; startup must fail fast if missing.
- DB outbox is canonical in runtime; the worker consumes the DB outbox.
- JSONL outbox (`INDEX_OUTBOX_PATH`) is audit/diagnostic only and must not be used as the worker queue.
- Registry watcher is the single runtime watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

## Watcher Operations

Use this section when the issue is specifically about watcher deployment, config, or execution mode.

### Docker-first deployment
1. Set `VAULT_ROOT` to your local vault path:
   `export VAULT_ROOT="/Users/you/PKM - Alpha"`
2. On macOS/iCloud-backed vaults, set container UID/GID mapping so watcher and worker can write UUID heals back into the vault:
   - `export LOCAL_UID=$(id -u)`
   - `export LOCAL_GID=$(id -g)`
   - recreate services after changes: `docker compose up -d --force-recreate watcher worker api`
3. Start the watcher service:
   ```bash
   docker compose up -d watcher
   ```
4. Follow logs:
   ```bash
   docker compose logs -f watcher
   ```

### Host fallback
- Run the registry watcher directly:
  ```bash
  WATCHER_ENABLE=1 WATCHER_VAULT_PATH="/path/to/vault" python -m app.cli watcher run
  ```
- Single-tick safety run:
  ```bash
  python -m app.cli watcher run --max-ticks 1
  ```
- Legacy snapshot watcher is lab-only and not part of runtime/start-system flows:
  ```bash
  PKM_SETTINGS_PROFILE=lab python -m app.cli vault-watcher-run --vault-root "<vault>" --snapshot-path "<state.json>"
  ```

### Key watcher env and defaults
- `WATCHER_ENABLE=1` arms the registry watcher.
- `WATCHER_VAULT_PATH` points at the vault root.
- `WATCHER_SCOPE_GLOB` overrides scan scope (default `**/*.md`).
- `VAULT_INBOX_DIR_REL` overrides inbox folder behavior when needed.
- `WATCHER_STATE_DIR` stores registry watcher state.
- `WATCHER_HEARTBEAT_PATH` and `WATCHER_TICK_LOG_PATH` control watcher health/tick outputs.
- `WATCHER_AUTO_EXEC=1` arms panel auto-exec; per-note opt-out remains `ai_panel_auto_run: never`.
- `PANEL_PROACTIVE_ASSIST=0|1` controls proactive panel creation.
- `WATCHER_STOP_FILE` pauses scanning when present.

### Watcher caveats
- The registry watcher remains polling/snapshot-based; no OS file-event hooks are used.
- Paths with spaces are supported; wrap vault paths in quotes.
- When using iCloud/Obsidian sync, keep scopes conservative and rely on debounce/backoff guardrails.
- Do not use the legacy snapshot watcher for runtime start-system flows.

## Runtime Compose Stack
- Canonical runtime compose stack: `db`, `api`, `watcher`, `worker`.
- `docker-compose.yaml` starts FastAPI (`api`), `worker`, `watcher`, and Postgres for local development.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data lives in the `postgres-data` volume; `docker compose down -v` wipes it.
- The API container runs `scripts/start_api.sh` (migrations + `uvicorn`).
- The worker runs `python -m app.workers.outbox_worker` (consumes DB outbox).
- The watcher runs `python -m app.cli watcher run` (registry loop; emits `ingest.vault.changed` or `panel.scan.requested` to outbox).
- Legacy dev stacks may include agent/redis containers; they are not part of the runtime start-system path.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Rotate them with `python scripts/rotate_storage.py [--dry-run|--copy|--truncate]`, which archives into `storage/archive/` by default and keeps a bounded history (`--max-backups`).
- Schedule the script (cron/systemd/GitHub Actions) to run routinely; review `--copy/--truncate` flags depending on whether live readers expect files to remain.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
- Use `--max-age-days` alongside `--max-backups` to purge old archives (set policy, e.g. 30 days).
- Run `pre-commit install` locally so lint/type/test hooks run automatically before each commit.
- Vector data now lives in Postgres (`objects` + `embeddings`); ensure the `pgvector` extension is installed and run `VACUUM ANALYZE embeddings` periodically as the cluster grows.

## Runtime Loop Runbook
1. **Start locally (compose)** – `make alpha-up` (requires `VAULT_ROOT`), or `docker compose up --build`.
2. **Health** – `python -m app.cli health --json` and `python -m app.cli status --json`.
3. **Watcher** – verify `WATCHER_ENABLE=1`, `WATCHER_VAULT_PATH`, and `INDEX_OUTBOX_PATH` in env; check `tmp/watcher_heartbeat.json`.
4. **Worker** – confirm `tmp/worker_heartbeat.json` updates and `processed_total` increases.
5. **Stop** – `docker compose down` or `make alpha-down`.

## Ingestion Review Runbook
1. **Prepare payload** – gather metadata in a JSON-compatible dict plus raw text under `text`.
2. **Ingest** – `python -m app.cli pipe <note.md>` or watcher-driven ingest via `vault-watcher-run`.
3. **Validate** – check `/api/status` + `/api/health` and confirm `index.embedding.created` events in outbox (legacy alias: `index.object.embedded`).
4. **Maintain** – run `python -m app.fitness.report` after major imports to watch latency and gate regressions.

## Auth & Rate Limiting
- Refer to `docs/SECURITY.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.

## Observability
- Logs: JSON-formatted via `app/observability.setup_logging()`. Hook into your logging stack (CloudWatch, ELK, etc.).
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
- Runtime signals and interpretation live in `docs/OBSERVABILITY.md`.
- Local Prometheus+Grafana recipe lives in `docs/INFRASTRUCTURE.md` (Docker Compose).

## Runtime health: watcher → DB outbox → worker
- Watcher heartbeat: `WATCHER_HEARTBEAT_PATH` (default `/app/tmp/watcher_heartbeat.json` in containers, `tmp/watcher_heartbeat.json` on host).
- Worker heartbeat: `WORKER_HEARTBEAT_PATH` (default `/app/tmp/worker_heartbeat.json`).
- DB outbox: check the `outbox` table for recent `ingest.vault.changed` and `panel.*` events; the worker should mark `delivered_at`.
- JSONL audit: `INDEX_OUTBOX_PATH` should append lines, but it is not the worker queue.
- Status: `python -m app.cli status` reports `worker_queue` vs `events_log` to distinguish DB vs JSONL.
- Health command semantics and degradation rules live in `docs/HEALTH.md`.

## Startup telemetry (startup_status.json)
- Location: `tmp/startup_status.json` (workspace root on the host).
- Lifecycle: written by `scripts/start_full_system.sh` on phase changes and in the cleanup trap; the last write happens on exit. Values are merged with the existing file; fields with explicit `None`/empty values are cleared when the writer marks them as clearable.
- Fields:
  - `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `timestamp` (last write). `started_at`/`ended_at` may appear when callers add them.
  - `llm_probe_step`, `llm_probe_cmd`, `llm_probe_rc`, `llm_probe_output_snippet`
  - `compose_up_step`, `compose_up_cmd`, `compose_up_rc`, `compose_up_output_snippet`
  - `db_probe_step`, `db_probe_cmd`, `db_probe_rc`, `db_probe_output_snippet`
- Debugging cold-start failures after `docker compose down`:
  - Bucket A: compose-up failure → check `compose_up_*` fields; expect `exit_reason=compose_up_failed` and a short `compose_up_output_snippet`.
  - Bucket B: db container/CID failure → `db_probe_step=compose_ps_db` and an empty/failed `db_probe_output_snippet`.
  - Bucket C: exec/psql timing failure → `db_probe_step=db_env_*` or `db_probe_rc!=0`; `db_probe_output_snippet` shows the failing exec/psql error.
- What to paste into an issue/PR comment: `timestamp`, `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `compose_up_*`, `db_probe_*`, `llm_probe_*`.

<!-- SECTION:OPS-RUNBOOKS:BEGIN -->
## Runbooks (quick reference)
| Issue | Symptom | Action |
| --- | --- | --- |
| yt-dlp 403/429 | Health passes but `transcribe` fails with `DownloadError` | Run `yt-dlp -v URL`, add cookies (`--cookies-from-browser`), or download via a piped host (see `docs/DEPENDENCIES.md`). |
| Missing ffmpeg | Health `ffmpeg=false`, CLI raises `CalledProcessError` | Install the package, verify with `which ffmpeg`. |
| Ollama offline | Health `ollama=false`, agent replies “Insufficient evidence” | Start `ollama serve`, `ollama pull <model>`, confirm via `curl $OLLAMA_URL/api/tags`. |
| `INDEX_OUTBOX_PATH` write failure | Health `index_outbox=false` | Fix filesystem permissions or point env to a writable directory. |

## SLO / SLA
| Level | Target | Measurement |
| --- | --- | --- |
| Ingestion latency | < 5 s from CLI start to DB outbox entry | Compare CLI start with `transcribe` / `agent.answer` spans. |
| Retrieval p95 | < 250 ms | `jq 'select(.node=="agent.answer") | .latency_ms'`. |
| ASR wall time | < 30 s for a 5-minute clip | `transcribe` span. |
| Health CLI | 100 % coverage before every release | Smoke step fails otherwise. |

## Incident handling (manual)
1. **Identify** – use `health` + `jq` to find the failing node.
2. **Stabilize** – set `LLM_PROVIDER=mock` or `STORE_BACKEND=memory` to keep working while debugging.
3. **Communicate** – add a short note to `docs/CHANGELOG.md` under “Unreleased incidents”.
4. **Restore** – restart Ollama/ffmpeg/CLI depending on the root cause. Restore `tmp/index-outbox.jsonl` from backup if corrupt (audit only).

## Backup / restore for index-outbox (audit log)
- Default path is `tmp/index-outbox.jsonl`. Simple rotation:
  ```bash
  cp tmp/index-outbox.jsonl "tmp/index-outbox.$(date +%Y%m%d%H%M%S).jsonl"
  truncate -s 0 tmp/index-outbox.jsonl
  ```
- In CI, archive the file as an artifact when needed.
- Restore: copy the file back and inspect via `python -m json.tool` (audit only; worker queue remains in DB).
<!-- SECTION:OPS-RUNBOOKS:END -->
