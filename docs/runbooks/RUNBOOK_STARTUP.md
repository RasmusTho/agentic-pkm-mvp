State: SoT v4.10 Reality-MVP (work branch prep).

# Startup Runbook

## 1. Config prerequisites
1. Expose the vault root: `export VAULT_ROOT=/path/to/vault` (or set in docker compose env file).
2. Seed `${VAULT_SYSTEM_DIR_REL}/Settings/health.md` so guided thresholds/incident logging exist (see `docs/HEALTH.md`).
3. Optional overrides: `INDEX_OUTBOX_PATH`, `HEALTH_THRESHOLDS_*` and `HEALTH_INCIDENT_CAPTURE_*` can guard tuning; keep `incident_log_path` in the vault to a known location you can tail.
4. `scripts/start_full_system.sh` refuses to proceed without `VAULT_ROOT`; set `ALLOW_LEGACY_VAULT=1` only when you deliberately want to fall back to `./vault` for short-lived demos. The script checks `docker info`, optionally starts Colima when `AUTO_START_COLIMA=1`, and uses `vault.layout.md` to derive `VAULT_INBOX_DIR_REL`/`VAULT_SYSTEM_DIR_REL` before exporting them to the container env so the watcher scopes the actual inbox.

## 2. Containers
1. Run `scripts/start_full_system.sh` to bring up the stack: it runs `docker compose up -d --build db api`, waits for `/healthz`, calls `python -m app.cli vault-layout-ensure` so the layout note exists, exports the resolved inbox/system folders (the banner prints `inbox=… system=…`), and then continues with `docker compose up -d --build watcher worker`.
2. When the script finishes, confirm the logs are warm using `docker compose logs -f api` / `docker compose logs -f worker` (CTRL+C once ready).
3. If you need to restart just the watcher/panel services, rerun the last stage manually: `docker compose up -d --build watcher worker` while `VAULT_INBOX_DIR_REL` is exported via `runtime.env`.

## 3. Health verification
1. `python -m app.cli health status --json` -> expect `state` running/catch_up, `writes_allowed=true`, doctor statuses non-fail, and `catch_up_progress`/`suggested_actions` reported. Repeat after any manual ingest or injection so `outbox_recent_age_s` shrinks again.
2. `INDEX_OUTBOX_PATH` is the append-only JSONL log used as the canonical outbox; the health contract reads its latest timestamp to determine `outbox_recent_age_s`. Make sure the file exists and is regularly appended to by the watcher/worker.
3. Tail the incident log yourself when troubleshooting: `tail -n 5 tmp/health-incidents.jsonl` (or the configured incident path) ensures the write guard can emit entries.
4. If health warns/fails, run the respective doctor commands (`python -m app.cli index doctor --json`, `python -m app.cli events doctor --json`) and follow suggested actions before proceeding.

## 4. What good looks like
- `health status` returns `state` running (or transient catch_up) with `writes_allowed` true and doctor statuses at `pass`. `suggested_actions` can be empty when stable.
- After ingesting a vault snapshot, `health status` should report `state` running (or transient catch_up) with `writes_allowed` true, `catch_up_progress` idle, and a short `outbox_recent_age_s`.

## DB sanity & worker verification
- `scripts/start_full_system.sh` now probes the DB container using `POSTGRES_USER`/`POSTGRES_DB` from inside the container (defaults: `app`/`app`) so it never assumes a `postgres` superuser. After readiness it runs `psql -c "select current_user, current_database();"` for a quick sanity check.
- Example commands to inspect the running services:
  ```bash
  docker exec -it "$(docker compose ps -q db)" sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
  tail -n 1 tmp/worker_heartbeat.json
  ```
- The host script also tails `tmp/worker_heartbeat.json` and prints the last line once the worker writes its heartbeat. Skip the probes with `SKIP_DB_PROBE=1` and/or `SKIP_WORKER_PROBE=1` when you only need to rebuild the stack.
- The vault layout detection order is `📥 Inbox`, `Inbox` (unless `VAULT_INBOX_DIR_REL`/`VAULT_SYSTEM_DIR_REL` are already set). The watcher uses the resolved folders so it never rescans the legacy `Inbox/System` tree.
- `python -m app.cli pipe <path>` now writes an `ingest.object.created` row directly into the DB outbox so the worker can react even without the watcher; set `PIPE_EMIT_DB_OUTBOX=0` to keep the CLI write limited to the local JSONL log.

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
- Embeddings now call `/api/embed` with `{"model":…,"input":[…],"truncate":true}` and fall back to `/v1/embeddings` when `/api/embed` returns HTTP 404/405/500+ or an HTTPX error; both paths assert the configured `EMBED_DIM` against the returned vector length.
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
