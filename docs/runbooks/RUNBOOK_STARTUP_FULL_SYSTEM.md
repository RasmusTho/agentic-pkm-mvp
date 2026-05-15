State: SoT v5.x forward line (full-system startup)
# Full System Startup (db + api + watcher + worker)

Use this runbook to bring up the Alpha Compose Runtime and validate runtime health before running gap tests or other checks.

Reading note:
- this runbook is about current startup and operator validation,
- not the full target-state architecture,
- and not a claim that the current compose/runtime wiring is the permanent system decomposition.

## Prod startup (canonical)

For the production runtime (`stable` channel against the real vault), use the `prod-start-full` target.
This uses the prod compose overlay, the `pkm-prod` project namespace, explicit `prod` environment, and an
operator-supplied `VAULT_ROOT`. Do not guess or substitute a dev/test vault path.

```bash
export VAULT_ROOT="/absolute/path/to/your/real/vault"
make prod-start-full
```

- API is exposed on host port **18000**.
- `VAULT_ROOT` must be set to the real operator vault path by the operator before startup.
- The prod runtime root is the repo checkout directory (e.g., `/Users/rasmus/workspace`), not a sub-directory. Ensure the correct worktree is used.

For LLM configuration when using a local Ollama endpoint via the OpenAI-compatible API (provider=`openai`):
- Set `OPENAI_BASE_URL` to the reachable Ollama base URL (e.g., `http://host.docker.internal:11434/v1`).
- Set `OPENAI_API_KEY` to a non-empty placeholder (e.g., `sk-local`).
- The runtime env generator derives `OPENAI_BASE` from `OPENAI_BASE_URL` automatically when not explicitly set.

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

## Config externalization follow-up

The current prod startup requires operators to supply LLM env vars (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, etc.)
manually before running the startup script. A separate settings/config gap-analysis PR will externalize
configuration through the existing settings model (`vault/@Settings/providers.md` and related surfaces).
Do not perform that gap analysis in this runbook; handle it through the standard docs-to-issue workflow.

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
  - rerun `make alpha-up` after fixing config/env.
