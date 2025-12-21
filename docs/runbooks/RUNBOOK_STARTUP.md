State: SoT v4.10 Reality-MVP (work branch prep).

# Startup Runbook

## 1. Config prerequisites
1. Expose the vault root: `export VAULT_ROOT=/path/to/vault` (or set in docker compose env file).
2. Seed `@System/Settings/health.md` so guided thresholds/incident logging exist (see `docs/HEALTH.md`).
3. Optional overrides: `INDEX_OUTBOX_PATH`, `HEALTH_THRESHOLDS_*` and `HEALTH_INCIDENT_CAPTURE_*` can guard tuning; keep `incident_log_path` in the vault to a known location you can tail.

## 2. Containers
1. Build & start the API + worker: `docker compose up -d --build api worker`.
2. (Optional) restart watcher/panel services if the deployment uses them: `docker compose up -d --build watcher`.
3. Confirm logs are warm using `docker compose logs -f api` / `docker compose logs -f worker` (CTRL+C once ready).

## 3. Health verification
1. `python -m app.cli health status --json` -> expect `state` running/catch_up, `writes_allowed=true`, doctor statuses non-fail, and `catch_up_progress`/`suggested_actions` reported. Repeat after any manual ingest to ensure no regressions.
2. `python -m app.cli health explain` -> human-friendly summary of state, writes guard, doctor hints, and latest catch-up progress.
3. `python -m app.cli health incidents tail --n 5` -> shows the most recent incident or `No incidents yet (path: …)` hint; ensures the incident log path is writable and discoverable.
4. If health warns/fails, run the respective doctor command full text (index: `python -m app.cli index doctor --json`, events: `python -m app.cli events doctor --json`) and follow suggested actions before proceeding.

## 4. What good looks like
- `health status` returns `state` running (or transient catch_up) with `writes_allowed` true and doctor statuses at `pass`. `suggested_actions` can be empty when stable.
- Incidents tail either prints recent JSON lines or explicitly says `No incidents yet (path: …)` (this indicates a clean slate).
- After ingesticing a vault snapshot, the `health explain` summary is readable, and any new incident lines appear within `tmp/health-incidents.jsonl` or the configured path.
