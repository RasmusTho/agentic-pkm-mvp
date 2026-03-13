State: forward line v5.x (registry watcher; Docker-first deployment). This is watcher-specific operational guidance.
# Watcher Operations

The runtime watcher is registry-based (config-driven) and runs via `python -m app.cli watcher run`. The legacy `vault-watcher-run`/`vault-watcher-daemon` snapshot watcher is lab-only (`PKM_SETTINGS_PROFILE=lab`) and deprecated for runtime/start system usage.

Use `docs/OPERATIONS.md` as the top-level runtime operations playbook. Use this document when the issue is specifically about watcher deployment, config, or execution mode.

## Docker-first deployment
1) Set `VAULT_ROOT` to your local vault path (quotes allow spaces):
   `export VAULT_ROOT="/Users/you/PKM - Alpha"`
- Note (macOS + iCloud vaults): set container uid/gid mapping so watchers/workers can write UUID heals back into the vault:
  - `export LOCAL_UID=$(id -u)`
  - `export LOCAL_GID=$(id -g)`
  - If you change these, recreate services: `docker compose up -d --force-recreate watcher worker api`

2) Start the watcher service:
   ```bash
   docker compose -f docker-compose.watcher.yml up -d watcher
   ```
   - Command: `python -m app.cli watcher run`
   - Config path defaults to `configs/watchers.yaml` (override with `WATCHER_CONFIG_PATH` or CLI `--config`).
   - State dir: `/state` via `WATCHER_STATE_DIR` (kept outside the vault).
   - Default scan scope is vault-wide markdown: `**/*.md` relative to `WATCHER_VAULT_PATH` (override with `WATCHER_SCOPE_GLOB`).
   - DB outbox: required when `STORE_BACKEND=pg` (set `DATABASE_URL` or `DB_DSN`).
   - JSONL outbox (`INDEX_OUTBOX_PATH`) remains an audit log; the worker consumes the DB outbox.
3) Logs:
   ```bash
   docker compose -f docker-compose.watcher.yml logs -f watcher
   ```

## Host fallback
- Run the registry watcher directly:
  ```bash
  WATCHER_ENABLE=1 WATCHER_VAULT_PATH="/path/to/vault" python -m app.cli watcher run
  ```
- Optional safety: `python -m app.cli watcher run --max-ticks 1` for a single scan loop.
- Legacy snapshot watcher (deprecated for runtime; lab-only):
  ```bash
  PKM_SETTINGS_PROFILE=lab python -m app.cli vault-watcher-run --vault-root "<vault>" --snapshot-path "<state.json>"
  ```

## Key env and defaults
- `WATCHER_ENABLE=1` arms the registry watcher.
- `WATCHER_VAULT_PATH` (default `vault`) points at the vault root.
- `WATCHER_SCOPE_GLOB` can override the scan scope (default: `**/*.md`).
- `VAULT_INBOX_DIR_REL` optionally overrides the inbox folder name for inbox-only behaviors (e.g., UUID healing); if unset, it is read from `vault.layout.md`.
- `WATCHER_STATE_DIR` stores registry watcher state (`/state` in Docker).
- `WATCHER_HEARTBEAT_PATH` defaults to `/app/tmp/watcher_heartbeat.json`.
- `WATCHER_TICK_LOG_PATH` defaults to `/app/tmp/watcher_tick.jsonl`.
- `WATCHER_AUTO_EXEC=1` arms panel auto-exec; `ai_panel_auto_run: never` opt-outs per note.
- `PANEL_PROACTIVE_ASSIST` (default `1`) allows creating an AI panel with proposals for eligible notes that have no `%%ai` fence yet. Set `PANEL_PROACTIVE_ASSIST=0` to disable proactive panel creation.
- `WATCHER_STOP_FILE` (default `/app/tmp/WATCHER_STOP`) pauses scanning when present.

## Notes and caveats
- The registry watcher remains polling/snapshot-based; no OS file-event hooks are used.
- Paths with spaces are supported; wrap `VAULT_ROOT` in quotes for Docker/env substitution.
- When using iCloud/Obsidian sync, keep scopes conservative and rely on debounce + backoff guardrails.
- If you need the legacy snapshot watcher for a one-off migration, do not use it for runtime start-system flows.
