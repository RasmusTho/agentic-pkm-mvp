State: SoT v5.x forward line (full-system startup)
# Full System Startup (db + api + watcher + worker)

Use this runbook to bring up the Alpha Compose Runtime and validate runtime health before running gap tests or other checks.

## Command-first startup
1. From repo root, run:
```
make alpha-up
```
2. The script:
   - `scripts/start_full_system.sh` runs `docker compose up -d db api worker watcher`
   - fails fast if `DATABASE_URL`/`DB_DSN` is missing (DB outbox is required for runtime)
   - waits for `/api/status` then `/api/health` to report runtime `db`/`worker`/`watcher` as ok (timeout 60s)
   - optional checks like `ffmpeg` are ignored by default via `STARTUP_IGNORE_CHECKS=ffmpeg` (set to `""` for strict mode)
   - on failure, prints `docker compose ps`, tails api/worker/watcher logs, and dumps `/api/health`

## Alpha Compose Runtime (canonical)
- Services: `db`, `api`, `watcher`, `worker`.
- The watcher writes audit JSONL events and enqueues DB outbox events (`ingest.vault.changed`, `promote.intent.created`).
- The worker consumes the DB outbox to perform ingest and promotion side effects, emitting `promote.done` on success.
- Status/health surfaces should be used for operator gating (`required_ok` is the primary signal).

Deprecated:
- `scripts/run_alpha_stack.sh` and `scripts/run_alpha_live.sh` are legacy helpers. Use `make alpha-up` instead.

## Watcher registry (multi-spec)
- Config file: `configs/watchers.yaml` (ships with `panel` + `ingest` watchers).
- Each watcher spec should include:
  - `name`
  - `scope_glob`
  - `debounce_ms`
  - `rate_limit_per_min`
  - `emit_event`
- Keep scopes conservative; run `scripts/gap_test_alpha.sh` after changing watcher specs.

## Interpreting /api/health (runtime)
- `watcher`: heartbeat from the registry includes `watchers` (names), `freshness_seconds`, and the shared outbox path.
- `worker`: heartbeat includes `processed_by_event` + `last_processed` (for `ingest.vault.changed`) plus `ticks_total`/`errors_total`.
- `db`: `ok` when Postgres reachable (`pg_isready`/ping via health).
- `llm`: `mock`/`skipped` unless `LLM_PROVIDER=ollama`.

Tests: `tests/e2e/test_operator_workflows.py::test_operator_can_diagnose_stale_worker`

## Heartbeat locations and freshness
- Watcher: `/app/tmp/watcher_heartbeat.json` (override with `WATCHER_HEARTBEAT_PATH`).
- Worker: `/app/tmp/worker_heartbeat.json` (override with `WORKER_HEARTBEAT_PATH`).
- Freshness threshold defaults to 60s per component (`*_HEARTBEAT_STALE_SECONDS`).
- Optional strict ingest check: set `HEALTH_REQUIRE_INGEST_WORKER=1` (and tune `INGEST_WORKER_STALE_SECONDS`).

## Recommended next steps
- Run the gap test after startup:
```
scripts/gap_test_alpha.sh
```
- If `/api/health` fails:
  - check heartbeat files in `/app/tmp`
  - `docker logs --tail 200 workspace-api-1|workspace-worker-1|workspace-watcher-1`
  - rerun `make alpha-up` after fixing config/env.
