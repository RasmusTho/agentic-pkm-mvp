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
1. Start here for runtime expectations, core checks, and escalation paths.
2. Follow `docs/HEALTH.md` when verifying readiness or diagnosing degraded state.
3. Follow `docs/OBSERVABILITY.md` for interpreting telemetry and counters.
4. Use `docs/INFRASTRUCTURE.md` when you need Docker/runtime topology, local startup flow, or the local monitoring stack.
5. Use `docs/runbooks/` only for task-specific walkthroughs after you have identified the affected runtime surface.

CLI note:
- `python -m app.cli --help` and `python -m app.cli <command> --help` remain the authoritative command discovery surface because the CLI evolves faster than the docs.
- Runtime verification note: `make verify-runtime` is the authoritative local operator check for the live Docker stack because it verifies service health plus in-container CLI health, rather than the host shell environment.

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Runtime prerequisites (registry watcher)
- `DATABASE_URL` or `DB_DSN` is required in runtime; startup must fail fast if missing.
- DB outbox is canonical in runtime; the worker consumes the DB outbox.
- JSONL outbox (`INDEX_OUTBOX_PATH`) is audit/diagnostic only and must not be used as the worker queue.
- Registry watcher is the single runtime watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

Current runtime path:
1. The registry watcher scans the vault and emits DB outbox events.
2. The worker consumes DB outbox rows and performs ingest/index work.
3. Health, status, and metrics confirm whether that path is healthy.

When the issue is startup topology or Compose wiring, switch to `docs/INFRASTRUCTURE.md`.
When the issue is signal interpretation, switch to `docs/OBSERVABILITY.md`.
When the issue is health semantics or degraded-state rules, switch to `docs/HEALTH.md`.

## Watcher Operations

Use this section only when the issue is specifically about watcher deployment, config, or execution mode.

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
- The legacy snapshot watcher remains lab-only and is not part of runtime/start-system flows. Do not use it for current runtime operation.

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

## Obsidian sync runtime

Current runtime model:
- Obsidian vault changes flow through the registry watcher into ingest/update events, then into the DB outbox and worker/indexer path
- runtime-side note writes must stay narrow: agreed frontmatter updates, AI panel mutations, inbox/log artifacts, and explicit maintenance writes
- `app/knowledge/write_ops.py` is the shared vault-write boundary for runtime/services; deeper transport details stay behind the knowledge-port abstractions

Operational rules:
- never treat note body rewrites as a normal sync action
- rename or move events should update canonical path state without forcing re-embedding when body content is unchanged
- delete propagation should emit explicit delete semantics only when the removed path was the UUID's last active file-state reference
- settings hot-reload should apply policy changes without restart, while invalid settings payloads should fail closed and preserve the previous active policy

Companion docs:
- `docs/HUMAN-FLOWS.md` for human-facing vault behavior constraints
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` for the note-write abstraction and adapter contract
- `docs/runbooks/UAT_PANEL_WATCHER.md` for a watcher/panel walkthrough

## Runtime Compose Stack
- Canonical runtime compose stack: `db`, `api`, `watcher`, `worker`.
- `docker-compose.yaml` starts FastAPI (`api`), `worker`, `watcher`, and Postgres for local development.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data lives in the `postgres-data` volume; `docker compose down -v` wipes it.
- The API container runs `scripts/start_api.sh` (migrations + `uvicorn`).
- The worker runs `python -m app.workers.outbox_worker` (consumes DB outbox).
- The watcher runs `python -m app.cli watcher run` (registry loop; emits `ingest.vault.changed` or `panel.scan.requested` to outbox).
- Legacy dev stacks may include agent/redis containers; they are not part of the runtime start-system path.
- `scripts/start_full_system.sh` is the supported startup wrapper. It now auto-probes Ollama reachability from inside the containerized runtime and persists the selected Docker-reachable endpoint into `tmp/runtime.env` before declaring startup healthy.
- When `LLM_PROVIDER=ollama`, startup tries the configured endpoint first, then Docker-safe candidates such as `host.docker.internal`, before failing the run.

Detailed startup, local topology, and recovery procedures live in `docs/INFRASTRUCTURE.md`.
Task-specific operator walkthroughs live in `docs/runbooks/`.

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

Operator triage order:
1. Run `make verify-runtime`.
2. If you need extra detail, run `docker compose exec -T api python -m app.cli health --json`.
3. Run `docker compose exec -T api python -m app.cli status`.
3. Check watcher and worker heartbeat files.
4. Inspect DB outbox freshness and `delivered_at`.
5. Escalate to `docs/INFRASTRUCTURE.md` or a task-specific runbook if the issue is startup/runtime-topology specific.

## Common operator CLI commands

Use `python -m app.cli <command> --help` for the full, current argument list. These are the stable operator-facing entrypoints:

| Command | Purpose |
| --- | --- |
| `health` | Local dependency and readiness checks (ffmpeg/yt-dlp/outbox/LLM reachability). |
| `status` | Human-readable runtime status snapshot for watcher/worker/outbox. |
| `watcher run` | Registry watcher loop for the runtime path. |
| `settings-validate` | Validate settings artifacts and compiled settings. |
| `settings-explain` | Show settings provenance and effective resolution. |
| `llm check` | Probe LLM/embedding endpoint reachability. |
| `pipe <note.md>` | Run ingest for a note/path outside the watcher loop. |
| `make verify-runtime` | Check container health plus in-container runtime health/status for the live Docker stack. |

Flow mapping:
- `python -m app.cli watcher run` -> watcher runtime
- `python -m app.cli ask` -> ASK flow (see `docs/HUMAN-FLOWS.md`)
- `python -m app.cli runtime-loop` -> legacy/dev-only runtime path, not part of current baseline operations

Useful examples:

```bash
LLM_PROVIDER=mock python -m app.cli health --json
python -m app.cli watcher run --max-ticks 1
python -m app.cli pipe notes/meeting.md
python -m app.cli settings-explain --json
```

Startup/runtime verification now treats task routes and embeddings explicitly:
- `checks.llm_task_routes` verifies the effective chat/reasoning/embed/eval routes for the current config.
- `checks.embedding_index` reports `rebuild_required=true|false` and the active/stored embedding identity relationship.
- `make verify-runtime` prints both the task-route summary and the embedding-index rebuild state from inside the containerized stack.

## Startup telemetry (startup_status.json)
- Location: `tmp/startup_status.json` (workspace root on the host).
- Lifecycle: written by `scripts/start_full_system.sh` on phase changes and in the cleanup trap; the last write happens on exit. Values are merged with the existing file; fields with explicit `None`/empty values are cleared when the writer marks them as clearable.
- Fields:
  - `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `timestamp` (last write). `started_at`/`ended_at` may appear when callers add them.
  - `startup_succeeded`, `runtime_verified`, `operator_interrupted`
  - `ollama_endpoint_repaired`, `ollama_endpoint_drift`, `ollama_configured_base_url`, `ollama_effective_base_url`, `ollama_endpoint_persist_hint`
  - `llm_probe_step`, `llm_probe_cmd`, `llm_probe_rc`, `llm_probe_output_snippet`
  - `compose_up_step`, `compose_up_cmd`, `compose_up_rc`, `compose_up_output_snippet`
  - `db_probe_step`, `db_probe_cmd`, `db_probe_rc`, `db_probe_output_snippet`
- Durable fix flow:
  - If startup auto-repairs the Ollama endpoint, run `make persist-runtime-repairs` to write the working endpoint back to `.env`.
- Debugging cold-start failures after `docker compose down`:
  - Bucket A: compose-up failure → check `compose_up_*` fields; expect `exit_reason=compose_up_failed` and a short `compose_up_output_snippet`.
  - Bucket B: db container/CID failure → `db_probe_step=compose_ps_db` and an empty/failed `db_probe_output_snippet`.
  - Bucket C: exec/psql timing failure → `db_probe_step=db_env_*` or `db_probe_rc!=0`; `db_probe_output_snippet` shows the failing exec/psql error.
- What to paste into an issue/PR comment: `timestamp`, `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `compose_up_*`, `db_probe_*`, `llm_probe_*`.

## Incident handling
1. Identify the failing surface with `health`, `status`, and heartbeat/outbox checks.
2. Stabilize the runtime by reducing optional integrations only if needed for diagnosis.
3. Record the incident in the active ticket or PR, and update `docs/STATUS.md` if current operational reality changed.
4. Use the relevant companion document or runbook for recovery details.

Quick issue routing:
- Missing dependency or local runtime startup issue -> `docs/INFRASTRUCTURE.md` and `docs/DEPENDENCIES.md`
- Health contract or degraded-state interpretation -> `docs/HEALTH.md`
- Metrics/logging interpretation -> `docs/OBSERVABILITY.md`
- Watcher/panel manual walkthrough -> `docs/runbooks/UAT_PANEL_WATCHER.md`
- Go-live/startup diagnostics -> `docs/runbooks/RUNBOOK_GO_LIVE.md`
