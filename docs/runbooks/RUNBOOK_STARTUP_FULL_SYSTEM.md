State: SoT v5.x forward line (full-system startup)
# Full System Startup (db + api + worker + watcher)

Use this runbook to bring up the baseline stack and validate runtime health before running gap tests or other checks.

## Command-first startup
1. From repo root, run:
```
scripts/start_full_system.sh
```
2. The script:
   - `docker compose up -d --build db api worker watcher`
   - waits for `/api/status` then `/api/health` to report runtime `db`/`worker`/`watcher` as ok (timeout 60s)
   - optional checks like `ffmpeg` are ignored by default via `STARTUP_IGNORE_CHECKS=ffmpeg` (set to `""` for strict mode)
   - on failure, prints `docker compose ps`, tails api/worker/watcher logs, and dumps `/api/health`.

## Interpreting /api/health (runtime)
- `watcher`: fresh `watcher_heartbeat.json` in `/app/tmp`; shows `freshness_seconds`, `ticks_total`, `errors_total`.
- `worker`: fresh `worker_heartbeat.json` in `/app/tmp`; includes `ticks_total`, `processed_total`, `errors_total`, `outbox_path`.
- `db`: `ok` when Postgres reachable (`pg_isready`/ping via health).
- `llm`: `mock`/`skipped` unless `LLM_PROVIDER=ollama`.

## Heartbeat locations and freshness
- Watcher: `/app/tmp/watcher_heartbeat.json` (override with `WATCHER_HEARTBEAT_PATH`).
- Worker: `/app/tmp/worker_heartbeat.json` (override with `WORKER_HEARTBEAT_PATH`).
- Freshness threshold defaults to 60s per component (`*_HEARTBEAT_STALE_SECONDS`).

## Recommended next steps
- Run the gap test after startup:
```
scripts/gap_test_alpha.sh
```
- If `/api/health` fails:
  - check heartbeat files in `/app/tmp`
  - `docker logs --tail 200 workspace-api-1|workspace-worker-1|workspace-watcher-1`
  - rerun `scripts/start_full_system.sh` after fixing config/env.
