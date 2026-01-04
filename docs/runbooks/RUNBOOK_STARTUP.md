State: SoT v4.10 Reality-MVP (work branch prep).

# Startup Runbook

## 1. Config prerequisites
1. Expose the vault root: `export VAULT_ROOT=/path/to/vault` (or set in docker compose env file).
2. Seed `${VAULT_SYSTEM_DIR_REL}/Settings/health.md` so guided thresholds/incident logging exist (see `docs/HEALTH.md`).
3. Optional overrides: `INDEX_OUTBOX_PATH`, `HEALTH_THRESHOLDS_*` and `HEALTH_INCIDENT_CAPTURE_*` can guard tuning; keep `incident_log_path` in the vault to a known location you can tail.

## 2. Containers
1. Build & start the API + worker: `docker compose up -d --build api worker`.
2. (Optional) restart watcher/panel services if the deployment uses them: `docker compose up -d --build watcher`.
3. Confirm logs are warm using `docker compose logs -f api` / `docker compose logs -f worker` (CTRL+C once ready).

## 3. Health verification
1. `python -m app.cli health status --json` -> expect `state` running/catch_up, `writes_allowed=true`, doctor statuses non-fail, and `catch_up_progress`/`suggested_actions` reported. Repeat after any manual ingest or injection so `outbox_recent_age_s` shrinks again.
2. `INDEX_OUTBOX_PATH` is the append-only JSONL log used as the canonical outbox; the health contract reads its latest timestamp to determine `outbox_recent_age_s`. Make sure the file exists and is regularly appended to by the watcher/worker.
3. Tail the incident log yourself when troubleshooting: `tail -n 5 tmp/health-incidents.jsonl` (or the configured incident path) ensures the write guard can emit entries.
4. If health warns/fails, run the respective doctor commands (`python -m app.cli index doctor --json`, `python -m app.cli events doctor --json`) and follow suggested actions before proceeding.

## 4. What good looks like
- `health status` returns `state` running (or transient catch_up) with `writes_allowed` true and doctor statuses at `pass`. `suggested_actions` can be empty when stable.
- After ingesting a vault snapshot, `health status` should report `state` running (or transient catch_up) with `writes_allowed` true, `catch_up_progress` idle, and a short `outbox_recent_age_s`.

## DB sanity & worker verification
- `scripts/start_full_system.sh` now probes the DB container using `POSTGRES_USER`/`POSTGRES_DB` from inside the container (defaults: `app`/`app`) so it never assumes a `postgres` superuser. After readiness it runs `psql -c \"select current_user, current_database();\"` for a quick sanity check.
- Example commands to inspect the running services:
  ```bash
  docker exec -it "$(docker compose ps -q db)" sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dt"'
  tail -n 1 tmp/worker_heartbeat.json
  ```
- The host script also tails `tmp/worker_heartbeat.json` and prints the last line once the worker writes its heartbeat. Skip the probes with `SKIP_DB_PROBE=1` and/or `SKIP_WORKER_PROBE=1` when you only need to rebuild the stack.

## 5. Host-based PG ingest fallback
1. When `scripts/ingest_alpha_inbox_pg.sh` reports `Errno 35`/`Resource deadlock` while reading the iCloud vault inside Docker, the mounted filesystem cannot be accessed reliably by the container; Docker/Colima deadlocks on macOS because the host lock is held by iCloud sync.
2. Run `scripts/ingest_alpha_inbox_pg_host.sh` instead: it reads the PKM - Alpha vault directly on the host and pushes events into PostgreSQL on `localhost:15432`, avoiding the Docker mount.
3. After the host script finishes, rerun `make alpha-up` (or `docker compose up -d --build db api worker watcher`) and verify `http://127.0.0.1:18000/api/status` plus `/api/ask` return sources.
4. Keep this script handy in ops guides whenever macOS + iCloud mounts are part of the stack; it mirrors the container-side ingest but always succeeds when Errno 35 would otherwise block progress.
