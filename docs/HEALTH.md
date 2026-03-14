State: SoT v5.5 Reality-MVP baseline locked. This document defines the health CLI behavior and runtime health contract.
# Health CLI & Contract

Fast way to verify local dependencies (`health`) and the runtime health contract snapshot that drives the worker write guard.

For top-level operational runbooks, use `docs/OPERATIONS.md`. For runtime telemetry interpretation beyond the health contract, use `docs/OBSERVABILITY.md`.

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
| `obsidian` | `app/cli/health.py` + `app/knowledge/health.py` | Obsidian CLI in `PATH` and installer compatibility (`>=1.12.4`) when knowledge policy requires Obsidian adapter | Install/update Obsidian installer and ensure `obsidian` command is available. |

## Health contract snapshot
```bash
python -m app.cli health status --json
```
- Emits the `HealthContract` snapshot (`state`, `reason`, `outbox_recent_age_s`, `catch_up_progress`, etc.).
- `catch_up_progress` reports how the worker interprets its active queue (DB outbox when `STORE_BACKEND=pg`), while the JSONL audit log (`INDEX_OUTBOX_PATH`) is used for lag/idle detection.
- The worker heartbeat file (`$WORKER_HEARTBEAT_PATH`) is the signal the Docker healthcheck verifies; the contract observes the latest heartbeat timestamp too.

- `catch_up_progress` now leans on `outbox_recent_age_s`, which is computed from the newest timestamp in the JSONL log. `catch_up` therefore means the worker has not seen new events within the configured thresholds rather than being stuck on the oldest record.
- When the newest outbox event age exceeds `outbox_degrade_oldest_age_s` for the configured sample count, the contract transitions to `degraded` with reason `outbox idle ...` and suggests running `events-doctor`.
- Runtime processing is driven by the DB outbox; `INDEX_OUTBOX_PATH` remains the append-only audit log. Clearing the JSONL file only affects audit/diagnostics and does not reset the DB queue.
- There is no `health explain` command in this release; use `python -m app.cli health status --json` (plus the health incident log) to understand why a state transition occurred.

## Span + logging
The command is wrapped with `@span("health.check")`, so health check runs are recorded in `docs/OBSERVABILITY.md`. Exceptions populate `extra.error`.

## CI behavior
- `.github/workflows/smoke.yml` runs the dependency check with `LLM_PROVIDER=mock`.
- Run `python -m app.cli health status --json` after manual ingestion to confirm `state` is `running` and that `catch_up_progress["processing_mode"]` is `idle` (or `replay` while the worker catches up).
<!-- SECTION:HEALTH:END -->
