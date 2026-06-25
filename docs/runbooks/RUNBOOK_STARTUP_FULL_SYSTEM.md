State: SoT v5.x forward line (full-system startup)
# Full System Startup (db + api + watcher + worker)

Use this runbook to bring up the full Compose stack and validate runtime health before running gap tests, acceptance checks, or other operator workflows.

Reading note:
- this runbook covers startup and operator validation only,
- not the full target-state architecture,
- and not a claim that the current compose/runtime wiring is the permanent system decomposition.

## Concept map: startup vs verification vs promotion vs rollback

These are four separate operations with different goals, risks, and rollback surfaces. Do not conflate them.

| Operation | What it does | Scope | Reversible? |
| --- | --- | --- | --- |
| **Startup** | Bring compose services up; wait for health gate | Code + config | Yes — `make prod-down` |
| **Verification** | Confirm running system is healthy and meets acceptance criteria | Running runtime | Yes — no state changes |
| **Promotion to test** | Move a commit into the test channel; apply migrations to `app_test` | Code ref + `app_test` DB | Yes, if migrations reversible |
| **Promotion to prod** | Move the `stable` ref; apply migrations to `app` DB; restart prod | Code ref + `app` DB | Conditional — forward-only migrations are irreversible |
| **Rollback** | Return `stable` to previous ref; reverse reversible migrations; restart | Code ref + DB schema | Partial — vault is never rewound (see §Vault is not release state) |

Startup and verification are safe to repeat. Promotion and rollback are operator-gated and produce audit receipts. Do not run a promotion as part of a normal startup.

## Startup command semantics

The repo provides several startup commands. Choose based on the channel and required isolation level.

| Command | Channel | Compose file | Project namespace | `PKM_ENVIRONMENT` | VAULT_ROOT required | Use when |
| --- | --- | --- | --- | --- | --- | --- |
| `make dev-start-full` | dev | `docker-compose.yaml:docker-compose.dev.yml` | `pkm-dev` | `dev` | From `.env.dev.local` | **Canonical dev startup.** Loads `.env.dev.local` for vault defaults; no inline path needed. |
| `make dev-up` | dev | `docker-compose.yaml:docker-compose.dev.yml` | `pkm-dev` | `dev` | No | Bring up dev containers only (no health-gate wait). Not a substitute for `dev-start-full`. |
| `make prod-start-full` | prod (`stable`) | `docker-compose.yaml:docker-compose.prod.yml` | `pkm-prod` | `prod` | From `.env.prod.local` | **Canonical prod startup.** Loads the configured Midgård prod vault default; no inline path needed. |
| `make prod-up` | prod | `docker-compose.yaml:docker-compose.prod.yml` | `pkm-prod` | `prod` | No | Bring up prod containers only (no health-gate wait). Not a substitute for `prod-start-full`. |
| `make test-start-full VAULT_ROOT=<path>` | test | `docker-compose.yaml:docker-compose.test.yml` | `pkm-test` | `test` | Yes | **Canonical test startup.** All four bindings explicit. Use for staged promotion verification (see `promote-to-test` skill). |
| `make test-up` | test | `docker-compose.yaml:docker-compose.test.yml` | `pkm-test` | `test` | Uses `TEST_VAULT_ROOT` | Bring up test containers only (no health-gate wait). Not a substitute for `test-start-full`. |
| `make start` | dev/test | `docker-compose.yaml` (base) | (default) | inherited | No — idles if unset | Generic local startup for dev/test iteration. As of #2005, `scripts/start_full_system.sh` boots a **no-vault idle posture** when `VAULT_ROOT` is unset (the watcher idles, the API serves the picker state) instead of exiting. A *set-but-missing* `VAULT_ROOT` still fails loud. |
| `make alpha-up VAULT_ROOT=<path>` | **Legacy.** Equivalent to the old prod startup before explicit env binding existed. Runs `scripts/start_full_system.sh` without explicit compose file, project name, or `PKM_ENVIRONMENT`. | — | — | — | Yes | **Do not use for new prod startups.** Use `make prod-start-full` instead. |
| `scripts/start_full_system.sh` | Varies | Inherits caller env | Inherits caller env | Inherits caller env | Caller-supplied | Core generic startup script. Do not call directly for prod; use `make prod-start-full` so the Midgård preflight runs before the generic no-vault-capable path. |

**Rule:** for a dev startup, use `make dev-start-full` (vault defaults from `.env.dev.local`). For a prod startup, use `make prod-start-full` (vault defaults from `.env.prod.local`). For a test-channel startup, use `make test-start-full VAULT_ROOT=<path>`. These targets enforce channel identity and run the health-gate wait. `make alpha-up` and bare `scripts/start_full_system.sh` calls lack one or more of these guarantees.

## Prod startup (canonical)

For the production runtime (`stable` channel against the real vault), use the `prod-start-full` target.
This uses the prod compose overlay, the `pkm-prod` project namespace, explicit `prod` environment, and an
operator-configured Midgård vault root from `.env.prod.local`. The `scripts/prod/start_midgard_stack.sh`
preflight fails before the generic no-vault-capable startup script if the configured vault is missing,
empty, or not Midgård. Do not guess or substitute a dev/test vault path.

```bash
make prod-start-full
```

- API is exposed on host port **18000**.
- `.env.prod.local` must set `VAULT_ROOT` to the real Midgård vault path once per machine.
- The prod runtime root is the repo checkout directory (e.g., `/path/to/repo`), not a sub-directory. Ensure the correct worktree is used.

For LLM configuration when using a local Ollama endpoint via the OpenAI-compatible API (provider=`openai`):
- Set `OPENAI_BASE_URL` to the reachable Ollama base URL (e.g., `http://host.docker.internal:11434/v1`).
- Set `OPENAI_API_KEY` to a non-empty placeholder (e.g., `sk-local`).
- The runtime env generator derives `OPENAI_BASE` (the full chat-completions URL used by the adapter) from `OPENAI_BASE_URL` by appending `/chat/completions`. An explicitly set `OPENAI_BASE` is written as-is and takes precedence.

## Dev startup (canonical — Niflheim vault or other dev vault)

Use `make dev-start-full` for the dev channel. This sets `PKM_ENVIRONMENT=dev`,
`COMPOSE_FILE=docker-compose.yaml:docker-compose.dev.yml`, and `COMPOSE_PROJECT_NAME=pkm-dev`. The vault root
comes from `.env.dev.local` (gitignored, never committed) which the operator creates once per machine.

### One-time setup: create `.env.dev.local`

```bash
cat > .env.dev.local <<'EOF'
PKM_ENVIRONMENT=dev
CHANNEL=dev
PKM_CHANNEL=dev
VAULT_ROOT=/Users/<you>/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim
VAULT_SYSTEM_DIR_REL=⚙️ System
VAULT_INBOX_DIR_REL=📥 Inbox
VAULT_DESK_DIR_REL=🛠️ Workbench
CANVAS_ENABLED=0
EOF
```

- Vault paths with spaces (e.g. iCloud `Mobile Documents`) are fully supported. Do NOT use shell
  quoting or `source` the file directly — the startup script uses a Python-based parser that handles
  spaces in values correctly.
- `.env.dev.local` is gitignored and must not be committed. It contains machine-specific absolute paths.
- The file format is Docker Compose env-file format (`KEY=VALUE`), not a shell script.
- Default dev vault: Niflheim. Default prod/stable vault: Midgård via `.env.prod.local`. Bifröst/test
  mapping is not a confirmed default; do not encode it without explicit operator confirmation.

### Dev startup after every reboot

```bash
make dev-start-full
```

This:
1. Detects `PKM_ENVIRONMENT=dev` and loads `.env.dev.local` **before** `.env`, so dev-specific
   `VAULT_ROOT` and layout vars take precedence.
2. Runs `scripts/start_full_system.sh` with the dev compose file and project name.
3. Emits resolved vault env to stdout before starting containers so the operator can verify.

The API is exposed on host port **18001** for the dev channel.

### Dev host preflight and safe `tmp/` cleanup

`scripts/start_full_system.sh` checks host free space before starting the flight recorder or running
Docker build/recreate work. The default guard:

- fails startup when the repo filesystem has less than **1024 MiB** free
  (`STARTUP_DISK_MIN_FREE_MIB`, default `1024`);
- warns when free space is below **5120 MiB** (`STARTUP_DISK_WARN_FREE_MIB`, default `5120`);
- checks the repo root by default (`STARTUP_DISK_CHECK_PATH`, default repo root);
- can be explicitly disabled with `STARTUP_DISK_CHECK=0` for a one-off operator recovery.

When the guard fails or Docker build fails with `No space left on device`, clean only dated
diagnostic files first:

```bash
find tmp -maxdepth 1 -type f \
  \( -name 'flightrecorder-*.log' -o -name 'watcher_tick-*.jsonl' \) \
  -delete
df -h .
```

These dated files are startup diagnostics and watcher tick captures. Do **not** routinely delete
live undated runtime files such as `tmp/runtime.env`, `tmp/startup_status.json`,
`tmp/index-outbox.jsonl`, `tmp/index.jsonl`, `tmp/watcher_tick.jsonl`,
`tmp/latest_watcher_tick_log`, worker/watcher heartbeat files, or `tmp-test/**` unless you are
intentionally following a reset runbook.

The same rule applies on Demerzel with Colima's 4 GiB VM: free host disk before rebuilding images.
If disk pressure wedged Docker or Colima, use the recovery sequence below after freeing space.

### Dev Colima/Docker recovery without touching prod

Use this only when Docker/Compose commands hang or fail fast while refreshing the dev channel.
Do not use prod targets and do not move the `stable` ref.

1. Confirm which channel ports are active from the host:

   ```bash
   lsof -nP -iTCP:18001 -sTCP:LISTEN || true   # dev API
   lsof -nP -iTCP:15433 -sTCP:LISTEN || true   # dev DB
   lsof -nP -iTCP:18000 -sTCP:LISTEN || true   # prod API
   lsof -nP -iTCP:15432 -sTCP:LISTEN || true   # prod DB
   ```

   If prod ports are active, stop and reassess before restarting Colima.

2. Check Docker/Colima responsiveness:

   ```bash
   docker version
   colima status
   LIMA_HOME="$HOME/.colima/_lima" limactl shell colima true
   ```

3. If only stale client commands are stuck, terminate those clients rather than containers:

   ```bash
   ps -ax -o pid,ppid,stat,etime,command |
     grep -E 'make dev-start-full|start_full_system|docker info|docker ps|docker compose|colima status' |
     grep -v grep
   ```

   Kill only the clearly stuck client/wrapper PIDs. Do not kill unrelated SSH, Colima, Docker, or
   prod processes based only on a port number.

4. Try graceful Colima recovery first:

   ```bash
   colima stop default
   colima start default
   docker version
   ```

5. If Colima is reported running but SSH resets or `colima stop` hangs, force-stop the Colima VM
   and restart it:

   ```bash
   LIMA_HOME="$HOME/.colima/_lima" limactl stop -f colima
   colima start default
   docker version
   ```

6. Restart only the dev stack:

   ```bash
   make dev-start-full
   curl -sS http://localhost:18001/healthz
   ```

### How channel-specific env loading works

When `PKM_ENVIRONMENT` (or `CHANNEL` / `PKM_CHANNEL`) is set, `start_full_system.sh` loads
`.env.${channel}.local` first, before `.env`. Since the loader uses defaults semantics (first writer
wins), the channel-specific file takes precedence. `.env` then fills in any remaining vars (LLM config,
Postgres credentials, etc.). This means `.env.dev.local` only needs to contain the vars that differ
from `.env` — typically `VAULT_ROOT` and vault layout dirs.

## Startup success verification

A successful startup writes a machine-readable receipt to `tmp/startup_status.json`.
A startup is complete and healthy when:

```json
{
  "startup_succeeded": true,
  "runtime_verified": true,
  "exit_code": 0,
  "phase": "done"
}
```

Check the receipt before enabling watcher auto-exec or accepting traffic.

## Command-first startup (dev/test)
1. From repo root, run:
```
make start
```
2. The script:
   - `scripts/start_full_system.sh` runs `docker compose up -d db api worker watcher`
   - fails fast if `DATABASE_URL`/`DB_DSN` is missing (DB outbox is required for runtime)
   - requires `LLM_PROVIDER` + `LLM_MODEL`; mock requires no endpoint, Ollama accepts `OLLAMA_URL` or `OPENAI_BASE_URL`, other providers require `OPENAI_BASE_URL`
   - waits for `/api/status` then `/api/health` to report runtime `db`/`worker`/`watcher` as ok (timeout 60s)
   - optional checks like `ffmpeg` are ignored by default via `STARTUP_IGNORE_CHECKS=ffmpeg` (set to `""` for strict mode)
   - Obsidian compatibility check runs by default (`STARTUP_CHECK_OBSIDIAN=1`) and reports pass/warning in startup telemetry; an Obsidian warning is **not** a startup blocker when `required=false` in the health output
   - optional strict Obsidian gate: set `STARTUP_ENFORCE_OBSIDIAN=1` to fail fast unless host Obsidian dependency checks pass (`obsidian` CLI + installer floor)
   - vault read/write probe runs inside the `api` container before watcher/worker startup; set `STARTUP_REQUIRE_VAULT_RW=1` to make rw probe failures fatal outside verify mode
   - on failure, prints `docker compose ps`, tails api/worker/watcher logs, and dumps `/api/health`
   - startup summary prints `obsidian gate: enabled=<...> status=<...>` and `tmp/startup_status.json` includes `obsidian_gate_enabled|ok|detail`

## LLM config source

Runtime env export resolves LLM provider defaults from the settings model (`vault/@Settings/providers.md`)
when raw env vars are not set. Operator env vars remain supported and override settings-derived values.
`OPENAI_BASE_URL`/`OPENAI_BASE` compatibility remains unchanged: explicit `OPENAI_BASE` wins, otherwise
`OPENAI_BASE` is derived from `OPENAI_BASE_URL`.

## Alpha Compose Runtime (canonical)
- Services: `db`, `api`, `watcher`, `worker`.
- The watcher runs the production-facing registry loop (`python -m app.cli watcher run`) and is environment-aware:
  - In `prod` (default), artifact paths and state are scoped to base directories (`tmp/`, `vault/`)
  - In `dev` (via `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`), artifact paths are scoped to `-dev` subdirectories (`tmp-dev/`, `vault-dev/`)
  - For the Compose runtime, watcher is deployed in a container and auto-selects environment based on inherited settings
- The watcher writes audit JSONL events and enqueues DB outbox events (`ingest.vault.changed`, `panel.scan.requested`).
- The worker consumes the DB outbox to perform ingest, panel, and promotion side effects, emitting `panel.intent.*`, `promote.intent.created`, and `promote.done` on success.
- Inbox UUID healing is performed by the worker on `ingest.vault.changed` for notes under the inbox folder (from `vault.layout.md` or `VAULT_INBOX_DIR_REL`) so notes do not linger without `uuid:` after a worker pass.
- Status/health surfaces should be used for operator gating (`required_ok` is the primary signal).
- Before widening watcher automation, run `python -m app.cli settings-explain --json` and `python -m app.cli status`; these are the canonical enablement checks for auto-exec posture.
- Treat `WATCHER_AUTO_EXEC=1` as necessary but not sufficient; corroborate it with allowlist validity, skip counters, and write-guard/provenance context.

Architectural reading note:
- this describes the current operational runtime loop,
- while the higher-level architecture still distinguishes interaction, cognition, execution, memory, and governance above these startup mechanics.

Deprecated:
- `scripts/run_alpha_stack.sh` and `scripts/run_alpha_live.sh` are legacy helpers. Use `make prod-start-full` (prod) or `make start` (dev/test) instead.
- `make alpha-up` is a legacy alias for the old prod startup without explicit env binding. Prefer `make prod-start-full`.

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
- Confirm watcher enablement posture after startup:
```
python -m app.cli settings-explain --json
python -m app.cli status
```
- Use the safe-to-enable checklist from those commands: effective auto-exec mode, allowlist validity, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed`.
- When startup verification is part of a merge/release path, also require the enforced CI summary line `CI SUMMARY GATES ok=true`.
- Run the gap test after startup:
```
scripts/gap_test_alpha.sh
```
- Run Obsidian boundary architecture guardrails:
```
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_obsidian_port_boundaries.py -m "not pg"
```
- For Obsidian-required server posture, export before startup:
```
export STARTUP_ENFORCE_OBSIDIAN=1
export KNOWLEDGE_PRIMARY_ADAPTER=obsidian_cli
export KNOWLEDGE_STRICT_STARTUP=1
export KNOWLEDGE_ALLOW_FALLBACK=0
```
- If `/api/health` fails:
  - check heartbeat files in `/app/tmp`
  - `docker logs --tail 200 workspace-api-1|workspace-worker-1|workspace-watcher-1`
  - rerun `make prod-start-full` (prod) or `make start` (dev/test) after fixing config/env.
