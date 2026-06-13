State: SoT v5.5 Reality-MVP baseline locked; v5.6 delivery line closed; this is the top-level operations entrypoint for the current runtime while v6.0 seams are shipped in bounded form and broader v6.1+ consumption remains planned.
Doc role: Core SoT
Authority: Top-level operator guidance for the current runtime; delegates specialized operational detail to linked companion docs but remains the main operational entrypoint.
Owner: Runtime / operator playbook
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-13
Last verified against: docs/STATUS.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/HEALTH.md, docs/INFRASTRUCTURE.md, docs/ENVIRONMENTS.md, docs/OBSERVABILITY.md, docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md, app/relevance/now_surface.py, tests/relevance/test_vault_native_moments.py, Makefile, scripts/verify_runtime_stack.sh, merged PR #1948, and current repo state at 811c9b97 on 2026-06-13
# Operations Playbook

Use this document as the operator-facing starting point for runtime operations.

Specialized companion documents:
- `docs/HEALTH.md` - health CLI behavior and runtime health contract
- `docs/OBSERVABILITY.md` - runtime observability signals, counters, and span/log contracts
- `docs/INFRASTRUCTURE.md` - local runtime stack, Docker/Colima setup, and local observability stack
- `docs/SECURITY_ARCHITECTURE.md` - security review routing, threat-model tiers, and security invariants

Reading order:
1. Start here for runtime expectations, core checks, and escalation paths.
2. Follow `docs/HEALTH.md` when verifying readiness or diagnosing degraded state.
3. Follow `docs/OBSERVABILITY.md` for interpreting telemetry and counters.
4. Use `docs/INFRASTRUCTURE.md` when you need Docker/runtime topology, local startup flow, or the local monitoring stack.
5. Use `docs/runbooks/` only for task-specific walkthroughs after you have identified the affected runtime surface.
6. Use `docs/ENVIRONMENTS.md` when the question is whether behavior belongs to `dev`, `test`, `prod`, or a boundary between them.
7. Use the parallel-stack recipe in `docs/ENVIRONMENTS.md` when you need to run `dev`, `test`, and `prod` Compose stacks simultaneously on one machine.
8. Use `docs/RELEASE_CHANNELS/README.md` plus the promotion skills when the question is stable/dev channel promotion, rollback, or prod-checkout pinning.
9. Use `docs/SECURITY_ARCHITECTURE.md` and `docs/security/API_SECURITY_MATRIX.md` before changing
   API exposure, auth/rate-limit posture, external provider/tool execution, or mutation-capable
   route behavior.

CLI note:
- `python -m app.cli --help` and `python -m app.cli <command> --help` remain the authoritative command discovery surface because the CLI evolves faster than the docs.
- Runtime verification note: `make verify-runtime` is the authoritative local operator check for the live Docker stack because it verifies service health plus in-container CLI health, rather than the host shell environment.
- Canvas note: `python -m app.cli canvas ...` and `/api/canvas/*` now exist as bounded session surfaces behind `CANVAS_ENABLED`; they are materially supported for bounded co-authoring, but still not part of the default production operator surface.

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.
- App-version bumps and git tags are separate from stable-channel promotion. When moving the `stable`
  ref, rehearsing rollback, or validating prod after a promotion, use
  `docs/RELEASE_CHANNELS/README.md` plus `prepare-promotion`, `execute-promotion`,
  `verify-promotion`, and `rollback-promotion`. For the full operator acceptance procedure
  (preflight, smoke test, soak, rollback rehearsal, and receipt), use
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`. Treat release channels as an operator-governed
  capability with outstanding feature acceptance, not as a fully accepted baseline workflow.

## Runtime prerequisites (registry watcher)
- `DATABASE_URL` or `DB_DSN` is required in runtime; startup must fail fast if missing.
- DB outbox is canonical in runtime; the worker consumes the DB outbox.
- JSONL outbox (`INDEX_OUTBOX_PATH`) is audit/diagnostic only and must not be used as the worker queue.
- Registry watcher is the single runtime watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

## Environment posture

This document is primarily the `prod` operator entrypoint.

Environment contract:
- `dev`, `test`, and `prod` are defined in `docs/ENVIRONMENTS.md`.
- Production operation means the runtime is acting against the operator's real vault and its production-facing runtime surfaces.
- The local `test` bootstrap path is the isolated verification posture, not production operation.
- Lab/dev-only flows, fixture vaults, legacy watcher paths, and reset-heavy workflows are not production operation even when they use the same codebase.

Operator rule:
- if a task depends on looser safety assumptions, mock providers, fixture stores, or lab-only tuning, treat it as `dev`
- if a task touches the real vault, production stores, or normal runtime startup/verification surfaces, treat it as `prod`

Current runtime path:
1. The registry watcher scans the vault, emits DB outbox events, and appends `watcher.run` audit rows so status can count runtime ticks.
2. The worker consumes DB outbox rows and performs ingest/index, panel scan, and promotion work, preserving bounded retries for transient missing or unstable notes before giving up.
3. Health, status, and metrics confirm whether that path is healthy.

## Canonical Local Test Bootstrap

The repo-supported local runtime verification path is the local `test` bootstrap golden path.

Use this path when you need a clean-state, repeatable verification run rather than flexible `dev` exploration:

1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack against that vault
5. verify health/status
6. run scripted UAT

Canonical command:

```bash
make test-bootstrap
```

Expanded command path:

```bash
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

Operational intent:
- this is the intended repo-supported path for local runtime verification
- `dev` remains the flexible local environment for exploration and debugging
- `test` is the isolated verification environment that should be resettable and reproducible
- the bootstrap path is itself part of the productized verification contract, not just setup glue
- startup, deterministic `make verify-runtime`, and scripted UAT/idempotence slices are shipped, so treat this path as the supported local verification lane while broader bootstrap hardening stays bounded to explicit follow-up slices

Use `docs/runbooks/UAT_PANEL_WATCHER.md` for the detailed walkthrough and `docs/runbooks/RUNBOOK_RESET_TO_ZERO.md` when you need the full reset semantics.

When the issue is startup topology or Compose wiring, switch to `docs/INFRASTRUCTURE.md`.
When the issue is signal interpretation, switch to `docs/OBSERVABILITY.md`.
When the issue is health semantics or degraded-state rules, switch to `docs/HEALTH.md`.

## Watcher Operations

Use this section only when the issue is specifically about watcher deployment, config, or execution mode.

### Watcher entrypoint classification

Entrypoints are explicitly classified by environment per `docs/ENVIRONMENTS.md`:

**Production-facing entrypoint:**
- `python -m app.cli watcher run` — canonical production registry watcher (prod/dev)
  - Multi-spec watcher registry loop, artifact path and state separation by environment
  - Supports both `prod` and `dev` environments via `PKM_ENVIRONMENT` or profile-based inference
  - This is the entrypoint for the current production baseline

**Dev-only legacy entrypoints (require `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`):**
- `python -m app.cli vault-watcher-run` — single-shot snapshot watcher (historical implementation)
- `python -m app.cli vault-watcher-daemon` — snapshot daemon (historical implementation)
- `python -m app.cli runtime-loop` — watcher → panel → promotion loop (historical test path)

The legacy entrypoints are retained for lab/dev workflows but should not be used for production operation. Use `watcher run` for all production-facing and standard dev runtimes.

Watcher auto-exec enablement rule:
- Treat `python -m app.cli settings-explain` plus `python -m app.cli status` as the canonical enablement check.
- `WATCHER_AUTO_EXEC=1` is necessary to arm panel auto-exec, but it is not sufficient on its own to prove rollout safety.
- Before enabling auto-exec for a wider runtime scope, confirm the effective allowlist, recent skip counters, and write-guard/provenance context are coherent across both CLI surfaces.
- When the question is release or merge readiness rather than a live local diagnosis, corroborate the operator view with the enforced CI summary line (`CI SUMMARY GATES ok=<bool>`).
- `python -m app.cli settings-validate` is the schema validation gate for repo-shipped panel action catalog/wiring and watcher settings. It rejects invalid panel action ids, missing required panel fields, malformed watcher `auto_run` values, and unknown watcher allowlist action ids.
- This validation path does not widen runtime authority: watcher auto-exec remains guarded by `WATCHER_AUTO_EXEC`, allowlist policy, and per-note `ai_panel_auto_run: never` opt-out.
- Sync-latency measurement mode is operator-scoped: keep `vault/@Settings/watchers.md` allowlist at default (`promote.evergreen`) and run harness/measurement sessions with `WATCHER_MEASUREMENT_MODE=1`. This temporarily appends `ingest.summary.create` during the run and returns to the default posture after the process exits.

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
- Registry watcher state is pruned back to the active scope on each tick so stale file history does not accumulate indefinitely.

### Watcher caveats
- The registry watcher remains polling/snapshot-based; no OS file-event hooks are used.
- Paths with spaces are supported; wrap vault paths in quotes.
- When using iCloud/Obsidian sync, keep scopes conservative and rely on debounce/backoff guardrails.
- Do not use the legacy snapshot watcher for runtime start-system flows.
- Do not treat lab/dev-only watcher paths as production equivalents.

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
- The watcher runs `python -m app.cli watcher run` (registry loop; emits `ingest.vault.changed` / `panel.scan.requested` DB outbox events and appends `watcher.run` audit rows to the JSONL event log).
- Legacy dev stacks may include agent/redis containers; they are not part of the runtime start-system path.
- `scripts/start_full_system.sh` is the supported startup wrapper. It now auto-probes Ollama reachability from inside the containerized runtime and persists the selected Docker-reachable endpoint into `tmp/runtime.env` before declaring startup healthy.
- When `LLM_PROVIDER=ollama`, startup tries the configured endpoint first, then Docker-safe candidates such as `host.docker.internal`, before failing the run.
- Companion UI channel launchers (`make dev-ui`, `make test-ui`, `make prod-ui`) bind the browser
  UI to `127.0.0.1` by default. Set `CUI_BIND_LAN=1` to explicitly opt into a `0.0.0.0`
  bind for trusted LAN/Tailscale UAT. Public internet exposure remains unsupported.

Detailed startup, local topology, and recovery procedures live in `docs/INFRASTRUCTURE.md`.
Task-specific operator walkthroughs live in `docs/runbooks/`.

## Auth & Rate Limiting
- Refer to `docs/SECURITY.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Use `docs/SECURITY_ARCHITECTURE.md` for security review routing and
  `docs/security/API_SECURITY_MATRIX.md` for route-by-route exposure and mutation classification.
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
- Settings gate view: `python -m app.cli settings-explain --json` is the canonical provenance and gate-resolution surface for watcher auto-exec, allowlist validity, and write guard context.
- Health command semantics and degradation rules live in `docs/HEALTH.md`.

## Event and queue troubleshooting
- Use the DB `outbox` table as the authoritative queue. Rows with `delivered_at is null` are pending
  or failed work; order them by `created_at` when reconstructing worker consumption order.
- Inspect the worker logs for `worker retry queued`, `worker retry exhausted`, `worker retry enqueue
  failed`, and `worker handler failed` messages. These are the current poison-message and retry
  observation points; there is no separate DLQ service in the active runtime.
- Promotion consumer failures should also surface as `promote.error` rows in the DB outbox or
  JSONL audit stream, with `source_event` and `trace_id` intact so the failed intent can be traced
  back to the originating input.
- Retry events carry `_worker_retry_count`, `_worker_retry_reason`, and
  `_worker_retry_enqueued_at` in the payload so operators can distinguish transient deferrals from
  fresh work.
- Use `event_id` to identify duplicate deliveries and `trace_id` to correlate watcher, worker,
  panel, promotion, and status/audit observations.
- Treat `INDEX_OUTBOX_PATH` JSONL lines as audit evidence only. A line in JSONL does not prove a DB
  outbox row is pending, delivered, or failed, and `python -m app.cli status` keeps
  `events_log` separate from `worker_queue` for that reason.

Operator triage order:
1. Run `make verify-runtime`.
2. If you need extra detail, run `docker compose exec -T api python -m app.cli health --json`.
3. Run `docker compose exec -T api python -m app.cli settings-explain --json` to confirm watcher gate state, allowlist validity, provenance, and write-guard context.
4. Run `docker compose exec -T api python -m app.cli status` to confirm watcher automation counters, last tick skips, last-run skip reasons, and panel-action/compiler provenance (source paths and combined digest).
5. Check watcher and worker heartbeat files.
6. Inspect DB outbox freshness and `delivered_at`.
7. For enablement decisions, treat `WATCHER_AUTO_EXEC` as necessary but not sufficient; corroborate with `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed`.
8. Escalate to `docs/INFRASTRUCTURE.md` or a task-specific runbook if the issue is startup/runtime-topology specific.

## Common operator CLI commands

Use `python -m app.cli <command> --help` for the full, current argument list. These are the stable operator-facing entrypoints:

| Command | Purpose |
| --- | --- |
| `health` | Local dependency and readiness checks (ffmpeg/yt-dlp/outbox/LLM reachability). |
| `status` | Human-readable runtime status snapshot for watcher/worker/outbox. |
| `watcher run` | Registry watcher loop for the runtime path. |
| `settings-validate` | Validate settings artifacts and compiled settings. |
| `settings-explain` | Show settings provenance and effective resolution. |
| `canvas open|edit|close` | Operate the bounded canvas co-authoring surface when `CANVAS_ENABLED=1`. |
| `llm check` | Probe LLM/embedding endpoint reachability. |
| `pipe <note.md>` | Run ingest for a note/path outside the watcher loop. |
| `pkm-alpha-ingest`, `vault-alpha-ingest` | Compatibility aliases for legacy startup and ingest callers; prefer the neutral ingest commands for new scripts. |
| `make verify-runtime` | Check container health plus in-container runtime health/status for the live Docker stack. |

Flow mapping:
- `python -m app.cli watcher run` -> watcher runtime
- `python -m app.cli ask` -> ASK flow (see `docs/HUMAN-FLOWS.md`)
- `python -m app.cli canvas open|edit|close` -> bounded canvas co-authoring surface (flagged; see `docs/HUMAN-FLOWS.md` and `docs/CANVAS_CHAT_SURFACE/README.md`)
- `python -m app.cli runtime-loop` -> legacy/dev-only runtime path, not part of current baseline operations

Useful examples:

```bash
LLM_PROVIDER=mock python -m app.cli health --json
python -m app.cli watcher run --max-ticks 1
python -m app.cli pipe notes/meeting.md
python -m app.cli settings-explain --json
python -m app.cli settings-validate
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
1. Identify the failing surface with `health`, `settings-explain`, `status`, and heartbeat/outbox checks.
2. Stabilize the runtime by reducing optional integrations only if needed for diagnosis.
3. If the incident concerns watcher auto-exec safety, record the observed allowlist, skip counters, write-guard/provenance state, and whether `CI SUMMARY GATES ok=<bool>` is green where CI is part of the rollout path.
4. Record whether the incident was observed in `dev` or `prod`, then update `docs/STATUS.md` if current operational reality changed.
5. Use the relevant companion document or runbook for recovery details.
6. For watcher, panel, or CLI-first orchestrator incidents on shipped current-state surfaces, use `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`.

Quick issue routing:
- Missing dependency or local runtime startup issue -> `docs/INFRASTRUCTURE.md` and `docs/DEPENDENCIES.md`
- Health contract or degraded-state interpretation -> `docs/HEALTH.md`
- Metrics/logging interpretation -> `docs/OBSERVABILITY.md`
- Watcher/panel/orchestrator incident triage -> `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`
- Watcher/panel manual walkthrough -> `docs/runbooks/UAT_PANEL_WATCHER.md`
- Go-live/startup diagnostics -> `docs/runbooks/RUNBOOK_GO_LIVE.md`
- Prod go-live acceptance (preflight through soak, rollback rehearsal, receipt) -> `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`

## Companion UI Entry Surfaces

- Current Companion UI operator-visible entry surfaces include the server-rendered System Entry Point substrate: entry-state declarations, latency-ladder re-entry treatment, unified topbar/overlay host, Panel command palette, governed capture modal, memory review drawer, read-only receipts history modal, system map overlay, opt-in guidance layer, settings drawer, and the state-gallery validation harness.
- Capture uses `POST /api/companion/capture`; it is a governed vault-inbox append through WriteGuard and `app.knowledge.write_ops`, with `capture.inbox.appended` emitted as metadata-only operational evidence.
- Memory review uses `GET /api/companion/memory/review-queue` and `POST /api/companion/memory/review-queue/{candidate_id}/decision`; accept/reject/revise are governed review outcomes, while defer remains non-terminal queue state.
- Parent #1782 is closed through #1795 validation. Operators should treat source-peek presentation, posture emphasis switching, and the context lane / place band as unshipped follow-ups unless a later owner-doc update promotes them.
