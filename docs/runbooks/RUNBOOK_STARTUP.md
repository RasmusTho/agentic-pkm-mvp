State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.


# Startup Runbook

## 1. Config prerequisites
1. Expose the vault root: `export VAULT_ROOT=/path/to/vault` (or set in docker compose env file).
   - macOS + iCloud vault mounts: set uid/gid mapping so containers can write UUID heals back into the vault:
     - `export LOCAL_UID=$(id -u)`
     - `export LOCAL_GID=$(id -g)`
     - If you change these, recreate services: `docker compose up -d --force-recreate api watcher worker`
2. Seed `${VAULT_SYSTEM_DIR_REL}/Settings/health.md` so guided thresholds/incident logging exist (see `docs/HEALTH.md`).
3. Optional overrides: `INDEX_OUTBOX_PATH`, `HEALTH_THRESHOLDS_*` and `HEALTH_INCIDENT_CAPTURE_*` can guard tuning; keep `incident_log_path` in the vault to a known location you can tail.
4. LLM preflight: `LLM_PROVIDER` + `LLM_MODEL` are required for runtime. `LLM_PROVIDER=mock` requires no endpoint vars. `LLM_PROVIDER=ollama` accepts `OLLAMA_URL` or `OPENAI_BASE_URL`. Other providers require `OPENAI_BASE_URL`.
5. `scripts/start_full_system.sh` enforces `VAULT_ROOT` (fail-fast unless `ALLOW_LEGACY_VAULT=1`) and uses `vault.layout.md` to resolve `VAULT_INBOX_DIR_REL`/`VAULT_SYSTEM_DIR_REL`. The resolved inbox is exported so the watcher scope defaults to that single folder. Runtime mode now starts `db`+`api`+`watcher`+`worker` by default; set `START_WATCHERS=0` and/or `START_WORKER=0` (or `START_MODE=infra`) when you need only API services.

## 2. Containers
1. Run `scripts/start_full_system.sh` to bring up the stack. The runtime default brings up `db`+`api`+`watcher`+`worker`, waits for `/healthz`, ensures the layout note, exports the derived `VAULT_INBOX_DIR_REL`/`VAULT_SYSTEM_DIR_REL`, and runs the same ingest/health/preflight probes as before.
2. Want to watch the inbox with tick diagnostics? `scripts/start_full_system.sh` rotates `WATCHER_TICK_LOG_PATH` (default `/app/tmp/watcher_tick-<timestamp>.jsonl` and mirrored in `tmp/latest_watcher_tick_log`), exports the path, and prints a `docker compose exec watcher` tail command so you can inspect every tick’s `scanned_files`, `hashed_files`, `bytes_read`, and guard status. The watcher scopes the scan root to the layout-derived Inbox, hashes notes only when their modification time changes, and applies `WATCHER_MAX_SCANNED_FILES_PER_TICK`, `WATCHER_MAX_BYTES_READ_PER_TICK`, and `WATCHER_MAX_ELAPSED_MS_PER_TICK` thresholds; exceeding those limits increases the sleep by `WATCHER_BAD_TICK_BACKOFF_SECONDS`, and `WATCHER_MAX_BAD_TICKS` consecutive bad ticks will create `/app/tmp/WATCHER_STOP` so you can investigate before deleting the file to resume.
3. When log data is stale or you want to smoke-test the watcher without Ollama or `/api/ask`, run `scripts/smoke_watcher_inbox.sh`. It creates a note under `@Smoke` in the resolved inbox with an AI fence and no uuid, runs a short watcher tick loop, asserts the note receives a uuid, and verifies a DB outbox event referencing the note was enqueued. Use it to validate that the watcher reacts quickly and keeps the scan limited to the inbox (JSONL outbox is audit-only).
4. When you need logs from the running services, tail `docker compose logs -f api` (and `worker`/`watcher` if enabled). The startup script also writes a timestamped log into `tmp/startup-logs/startup-<timestamp>.log` that captures `docker info`, `docker compose ps`, the last 200 lines of any enabled service logs, the resolved layout, and the latest worker heartbeat snapshot.
5. If you need to restart only the watcher or panel services manually, rerun `docker compose up -d --build watcher worker` with `VAULT_INBOX_DIR_REL` exported via the generated `runtime.env`.
6. Guard the watcher controls with the regression marker command so watchdog failures are caught quickly: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory pytest -q -m watcher_controls`. If the marker ever drifts, the direct fallback `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory pytest -q tests/watcher/test_watcher_controls.py tests/watcher/test_registry_guardrails.py` (or `scripts/test_watcher_controls.sh`) exercises the inbox-bounded scan, mtime gating, and stop-file/backoff guardrails without running unrelated suites.
7. Flight recorder: `scripts/start_full_system.sh` starts `scripts/flight_recorder.sh` (default `START_FLIGHT_RECORDER=1`) before any Docker/`VAULT_ROOT` checks, so you still capture host diagnostics even if Docker is down or `VAULT_ROOT` is unset. The recorder writes `tmp/flightrecorder-<timestamp>.log` outside the vault every ~5s; each entry dumps `uptime`, `top`, `ps`, `df`, and docker info/logs so you can postmortem a hard reset. When diagnosing a hang, tail `tail -n 40 tmp/flightrecorder-<timestamp>.log` plus the watcher tick log, and include that file when reporting the issue. Use `scripts/flight_recorder.sh --once` (and the `--interval`/`--duration` knobs) for a single snapshot even on hosts without docker. Run `scripts/test_flight_recorder_invariant.sh` when you tweak startup to verify the recorder still creates `tmp/flightrecorder-*.log` despite an early failure.

### Minimal safe bring-up
```bash
export VAULT_ROOT=/path/to/vault
START_WATCHERS=0 START_WORKER=0 scripts/start_full_system.sh
```
This sequence keeps watchers/workers off the grid while still validating `/healthz`, ingest/search, and the host-side diagnostics log.

### Full system bring-up
```bash
export VAULT_ROOT=/path/to/vault
scripts/start_full_system.sh
```
Runtime defaults to watchers + worker after layout detection so they can begin scanning the layout-derived inbox scope. Set `START_WATCHERS=0` or `START_WORKER=0` if you need to disable either service.

## 3. Health verification
1. `python -m app.cli health status --json` -> expect `state` running/catch_up, `writes_allowed=true`, doctor statuses non-fail, and `catch_up_progress`/`suggested_actions` reported. Repeat after any manual ingest or injection so `outbox_recent_age_s` shrinks again.
2. DB outbox is the canonical worker queue; `INDEX_OUTBOX_PATH` is the append-only audit log. Health surfaces both (`worker_queue` vs `events_log`), so ensure DB connectivity and that the JSONL log is still being appended to by the watcher.
3. Tail the incident log yourself when troubleshooting: `tail -n 5 tmp/health-incidents.jsonl` (or the configured incident path) ensures the write guard can emit entries.
4. If health warns/fails, run the respective doctor commands (`python -m app.cli index doctor --json`, `python -m app.cli events doctor --json`) and follow suggested actions before proceeding.

## 4. What good looks like
- `health status` returns `state` running (or transient catch_up) with `writes_allowed` true and doctor statuses at `pass`. `suggested_actions` can be empty when stable.
- After ingesting a vault snapshot, `health status` should report `state` running (or transient catch_up) with `writes_allowed` true, `catch_up_progress` idle, and a short `outbox_recent_age_s`.
- The watcher resolves its scan root from the layout note, keeps scope to `${INBOX_FOLDER}/**`, and hashes notes only when their modification time actually changes; every tick records a compact JSON line in `${WATCHER_TICK_LOG_PATH:-/app/tmp/watcher_tick.jsonl}` so you can inspect `scanned_files`, `hashed_files`, `bytes_read`, etc. after a hard reset.

## DB sanity & worker verification
- `scripts/start_full_system.sh` probes the DB container using `POSTGRES_USER`/`POSTGRES_DB` from inside the container (defaults: `app`/`app`) so it never assumes a `postgres` superuser. After readiness it runs `psql -c "select current_user, current_database();"` for a quick sanity check.
- Example commands to inspect the running services:
  ```bash
  docker exec -it "$(docker compose ps -q db)" sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dt"'
  tail -n 1 tmp/worker_heartbeat.json
  ```
- The host script also tails `tmp/worker_heartbeat.json` and prints the last line once the worker writes its heartbeat. Skip the probes with `SKIP_DB_PROBE=1` and/or `SKIP_WORKER_PROBE=1` when you only need to rebuild the stack.
- The vault layout detection reads the `vault.layout.md` note that `vault-layout-ensure` guarantees; the derived `VAULT_INBOX_DIR_REL`/`VAULT_SYSTEM_DIR_REL` (and their watcher-scope exports) ensure the watcher only scans `${INBOX_FOLDER}/**`. Legacy heuristics (`Inbox`, `📥 Inbox`) are ignored unless you intentionally run with `ALLOW_LEGACY_VAULT=1`.
- `python -m app.cli pipe <path>` writes an `ingest.object.created` row directly into the DB outbox so the worker can react even without the watcher; set `PIPE_EMIT_DB_OUTBOX=0` to keep the CLI write limited to the local JSONL log.

## Ollama readiness
- `scripts/start_full_system.sh` runs an httpx-based preflight inside the API container (GET `/api/tags` + POST `/api/embed` with `["startup-check"]`) before the bootstrap run; failures print a warning and `/api/ask` is skipped. To rerun manually, execute the same python probe via:
```bash
docker compose exec -T api python - <<'PY'
import os, sys
import httpx

base = os.environ.get("OLLAMA_URL")
if not base:
    print("OLLAMA_URL missing", file=sys.stderr)
    raise SystemExit(2)
model = os.environ.get("OLLAMA_EMBED_MODEL") or os.environ.get("EMBED_MODEL", "nomic-embed-text:latest")
with httpx.Client(timeout=10.0) as client:
    client.get(f"{base}/api/tags").raise_for_status()
    resp = client.post(
        f"{base}/api/embed",
        json={"model": model, "input": ["startup-check"], "truncate": True},
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("embeddings") or data.get("embedding")
    if not candidates:
        raise SystemExit(3)
    entry = candidates[0] if isinstance(candidates, list) and isinstance(candidates[0], (list, tuple)) else candidates
    print("Ollama embed dim:", len(entry))
PY
```
- Embeddings now call `/api/embed` with `{"model":…, "input": […], "truncate": true}` and fall back to `/v1/embeddings` when `/api/embed` returns HTTP 404/405/500+ or an HTTPX error; both paths assert the configured `EMBED_DIM` against the returned vector length.
- Skip the smoke notes under `/app/tmp`; the real `scripts/smoke_vault_ingest.sh` writes into `/app/vault/<inbox>/@Smoke` so you can prove the watcher + worker react to the same inbox that powers `/api/ask`.

## Vault layout & smoke notes
- `scripts/start_full_system.sh` calls `python -m app.cli vault-layout-ensure --vault-root /app/vault` before spinning up watcher/worker, exports the json output paths, and prints a banner like `--- VAULT LAYOUT --- inbox: 📥 Inbox system: ⚙️ System`.
- The helper `scripts/smoke_vault_ingest.sh` mirrors the same inbox detection order and writes a brief note to `/app/vault/<inbox>/@Smoke/smoke-<timestamp>.md`. It runs `python -m app.cli pipe <path> --json`, asserts the `ingest.object.created` row is in the DB outbox, and waits for the worker to mark `delivered_at` so you know the event was processed.
- Use the smoke script whenever you want a fast, deterministic proof that the runtime is watching the real vault rather than `/app/tmp` or a temporary note store.

## 5. Host-based PG ingest fallback
1. When `scripts/ingest_alpha_inbox_pg.sh` reports `Errno 35`/`Resource deadlock` while reading the iCloud vault inside Docker, the mounted filesystem cannot be accessed reliably by the container; Docker/Colima deadlocks on macOS because the host lock is held by iCloud sync.
2. Run `scripts/ingest_alpha_inbox_pg_host.sh` instead: it reads the PKM - Alpha vault directly on the host and pushes events into PostgreSQL on `localhost:15432`, avoiding the Docker mount.
3. After the host script finishes, rerun `make alpha-up` (or `docker compose up -d --build db api worker watcher`) and verify `http://127.0.0.1:18000/api/status` plus `/api/ask` return sources.
4. Keep this script handy in ops guides whenever macOS + iCloud mounts are part of the stack; it mirrors the container-side ingest but always succeeds when Errno 35 would otherwise block progress.