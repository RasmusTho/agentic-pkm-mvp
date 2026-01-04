State: SoT v4.10 Reality-MVP (current).
# Health CLI & Contract

Fast way to verify local dependencies (`health`) and the runtime health contract snapshot that drives the worker write guard.

<!-- SECTION:HEALTH:BEGIN -->
## Dependency checks
```bash
python -m app.cli health --json
```
- Returns `{"ok": bool, "checks": {...}, "trace_id": "..."}`.
- Exit code `0` when all checks pass, otherwise `1`.
- Use `--trace-id TRACE123` to correlate with other logs.

| Key | Source | What is validated | Remediation |
| --- | --- | --- | --- |
| `ffmpeg` | `app/cli/health.py:20-28` | `shutil.which("ffmpeg")` | Install via a package manager (`brew install ffmpeg` or `apt`). |
| `yt_dlp` | `app/cli/health.py:30-36` | Module import | `pip install -r requirements.txt`. |
| `index_outbox` | `app/cli/health.py:38-46` | Write access to `INDEX_OUTBOX_PATH` (creates directories when missing) | Fix permissions or adjust the env path. |
| `ollama` | `app/cli/health.py:48-49` | GET `${OLLAMA_URL}/api/tags` when `LLM_PROVIDER=ollama`; skipped otherwise | Start Ollama or switch to `LLM_PROVIDER=mock`. |

## Health contract snapshot
```bash
python -m app.cli health status --json
```
- Emits the `HealthContract` snapshot (`state`, `reason`, `outbox_recent_age_s`, `catch_up_progress`, etc.).
- `catch_up_progress` reports how the worker interprets `INDEX_OUTBOX_PATH`: it is the append-only JSONL log that records events/ingests, not a queue.
- The worker heartbeat file (`$WORKER_HEARTBEAT_PATH`) is the signal the Docker healthcheck verifies; the contract observes the latest heartbeat timestamp too.

## Span + logging
The command is wrapped with `@span("health.check")`, so health check runs are recorded in `docs/OBSERVABILITY.md`. Exceptions populate `extra.error`.

## CI behavior
- `.github/workflows/smoke.yml` runs the dependency check with `LLM_PROVIDER=mock`.
- Run `python -m app.cli health status --json` after manual ingestion to confirm `state` is `running` and that `catch_up_progress["processing_mode"]` is `idle` (or `replay` while the worker catches up).
<!-- SECTION:HEALTH:END -->
