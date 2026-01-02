State: SoT v5.x forward line (runtime gap test ready)
# Runtime Gap Test

This runbook documents the CLI-driven regression smoke that ensures a single vault edit flows through the Entire Chain (watcher → worker → index → `/api/ask`).

## When to run
- After changing Docker Compose, watcher configs, worker ingest logic, or API routes that touch the outbox/heartbeat paths.
- Before merging infra/ops PRs that touch connectors, watchers, or the gap test tooling.

## How to run

1. Make sure the stack is running, for example via `scripts/start_full_system.sh`.
2. Run the gap test script:
```
scripts/gap_test_alpha.sh
```
3. Optional arguments:
   - `NOTE_REL` (default `${VAULT_INBOX_DIR_REL}/_gap_test.md`) places the marker in another vault subpath.
   - `API_BASE_URL` points to a non-local API instance if you have a custom endpoint.

## Expectations
1. The script writes a note under the vault path with YAML frontmatter and a fresh `GAP_TEST_MARKER` token.
2. It polls `/api/events/tail?topic=panel.scan.requested&limit=50` until a watcher-emitted `panel.scan.requested` event mentions the marker note path.
3. It posts a JSON payload to `/api/ask`, and the response must include at least one source whose relative path (or path suffix) includes the marker note path and whose answer echoes the marker line.
4. If any step fails, diagnostics show `/api/status`, `/api/health`, and the relevant events tails, so operators can triage missing watcher or worker signals.

## Diagnostics bundle
If the script exits with `1` or `2`, the printed diagnostics include:
- `/api/status` and `/api/health` pretty-printed via `python3 -m json.tool` (or `python` fallback).
- `/api/events/tail?topic=panel.scan.requested&limit=50` for the watcher signal.
- `/api/events/tail?topic=index.object.embedded&limit=50` for downstream index events.

## Exit codes
- `0` — success: `/api/ask` reported the marker note path as a source and echoed the marker line.
- `2` — `/api/ask` had zero sources or none matching the marker note after retries; rerun after ensuring the worker/index pipeline processes the note.
- `1` — hard failure such as missing watcher events, HTTP errors, or JSON parsing issues; consult the diagnostics to investigate.

## Notes
- The script is bash 3.2 compatible; all JSON parsing and matching happens inside Python helpers, so macOS users can run it without Bash 4+ features.
- Keep the stack healthy with `scripts/start_full_system.sh` before running the gap test to ensure watchers, worker, and API routes are aligned.
