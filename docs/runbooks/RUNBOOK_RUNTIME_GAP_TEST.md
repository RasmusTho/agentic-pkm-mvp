State: SoT v5.x forward line (runtime gap test ready)
# Runtime Gap Test

Ensures the watcher → outbox → worker → index → /api/ask path stays healthy after compose or workflow changes.

## When to run
- After editing `docker-compose.yaml`, watcher, worker, or API logic that touches the outbox/heartbeat paths.
- Before merging ops/infra PRs that touch connectors (DB, watcher, index rebuild, CLI endpoints).

## How to run

1. Start the full system first:
```
scripts/start_full_system.sh
```
2. Then run the gap test:
```
scripts/gap_test_alpha.sh
```

Optional arguments:
- `NOTE_REL` (default `@Inbox/_gap_test.md`) allows placing the marker in another vault folder.

## Expected output
1. The script writes `GAP_TEST_MARKER: ...` into the target note and prints its absolute path.
2. The watcher container shows new outbox entries containing `watcher.` events or the marker note path.
3. Worker stats show the index-outbox file changing, and the script prints the last 120 worker log lines.
4. API `/api/health` and `/api/status` payloads are emitted, and `curl` to `/api/ask` returns at least one source referencing the vault note (or at least one entry from the sources array).

If an embedding/index rebuild was required, the script performs `python -m app.cli index rebuild --backend pg` inside the API container and reruns the ask check.

## Common failure modes
- `watcher` heartbeat missing or outbox tail remains unchanged: check `workspace-watcher-1` logs and ensure the heartbeat path (`/app/tmp/watcher_heartbeat.json`) is writable.
- Worker stats/logs do not update: the worker may be stuck waiting on Kafka/outbox or `worker` service might be unhealthy.
- `/api/ask` returns zero sources: embeddings/index may need rebuild, or the index service might not yet have processed the test note.
- The container stack cannot reach `http://127.0.0.1:18000`: confirm all services are running via `docker compose ps` and restart the stack if necessary.

## Compatibility
- Designed to run on macOS default Bash 3.2 / sh-compatible environments; JSON parsing and matching happens in Python to avoid Bash 4+ features like `mapfile`.
- Uses Docker/compose and the `curl` + `python` toolchain already expected in the Reality-MVP stack.

## Exit codes
- `0` — success and `/api/ask` returned at least one source that mentions the gap marker or the vault note path.
- `1` — hard failure (watcher/outbox/containers failed to progress or JSON parsing raised an unexpected error); inspect the printed diagnostics.
- `2` — `/api/ask` produced zero sources or none contained the marker path after the retry loop; rerun after ensuring the watcher/worker/index chain is healthy or rebuild the index via the script’s built-in `python -m app.cli index rebuild --backend pg` command (already part of the run). Corner cases report the diagnostics bundle printed before exit.
