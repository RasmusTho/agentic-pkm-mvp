State: forward line v5.x (watcher track v5.1–v5.4; Docker-first deployment option added in v5.5B)
# Vault Watcher Operations

The vault watcher is polling/snapshot-based (no OS file events). It can run as:
- a long-running Docker service (preferred), or
- a host service (e.g., launchd/systemd) when mounted volumes (iCloud/Obsidian) are unreliable.

## Docker-first deployment
1) Set `VAULT_ROOT` to your local vault path (quotes allow spaces):  
   `export VAULT_ROOT="/Users/you/PKM - Alpha"`
2) Start the watcher service:
   ```bash
   docker compose -f docker-compose.watcher.yml up -d watcher
   ```
   - Command: `python -m app.cli vault-watcher-daemon --vault-root /vault --poll-seconds 5 --cooldown-seconds 10 --max-notes 20`
   - Snapshot path defaults to `/state/vault_watcher_state.json` (kept outside the vault).
   - Volumes: `${VAULT_ROOT}:/vault` (bind) and `watcher_state:/state` (snapshot).
   - Env defaults: `STORE_BACKEND=memory`, `LLM_PROVIDER=mock` (override as needed).
3) Logs:
   ```bash
   docker compose -f docker-compose.watcher.yml logs -f watcher
   ```

## Host fallback (launchd/systemd)
- Use `python -m app.cli vault-watcher-daemon --vault-root "<path with spaces>" --snapshot-path "<state path>"`.
- Keep `--cooldown-seconds` > `--poll-seconds` when using iCloud/Obsidian to avoid rapid reprocessing on slow syncs.
- If long-running services are undesired, continue to use the single-shot CLI:
  ```bash
  python -m app.cli vault-watcher-run --vault-root "<vault>" --snapshot-path "<state.json>"
  ```

## Flags and defaults
- `vault-watcher-daemon`
  - `--vault-root` (required)
  - `--snapshot-path` (default `/state/vault_watcher_state.json`)
  - `--poll-seconds` (default 30) — used when no changes are detected
  - `--cooldown-seconds` (default 10) — used after a run with changes
  - `--max-notes` / `--force` safety guard
  - `--skip-panel` / `--emit-only` passed through to panel runtime
- `vault-watcher-run` (single-shot) keeps existing defaults; snapshot defaults to `<vault>/.agentic-pkm/vault_watcher_state.json`.

## Notes and caveats
- The watcher remains polling/snapshot-based; no OS file-event hooks are used.
- Paths with spaces are supported; wrap `VAULT_ROOT` in quotes for Docker/env substitution.
- When using iCloud/Obsidian sync, prefer `--cooldown-seconds` to avoid thrashing on partially-synced files.
- Snapshot storage outside the vault is recommended for Docker (`/state`) to keep the vault clean.
