# Health CLI

Fast way to verify local dependencies before running the ingestion / agent pipeline.

<!-- SECTION:HEALTH:BEGIN -->
## Usage
```bash
python -m app.cli health --json
```
- Returns `{"ok": bool, "checks": {...}, "trace_id": "..."}`.
- Exit code `0` when all checks pass, otherwise `1`.
- Use `--trace-id TRACE123` to correlate with other logs.

## Checks
| Key | Source | What is validated | Remediation |
| --- | --- | --- | --- |
| `ffmpeg` | `app/cli/health.py:20-28` | `shutil.which("ffmpeg")` | Install via package manager (`brew install ffmpeg` or apt). |
| `yt_dlp` | `app/cli/health.py:30-36` | Module import | `pip install -r requirements.txt`. |
| `index_outbox` | `app/cli/health.py:38-46` | Write access to `INDEX_OUTBOX_PATH` (creates dirs if missing) | Adjust env / filesystem permissions. |
| `ollama` | `app/cli/health.py:48-49` | GET `${OLLAMA_URL}/api/tags` when `LLM_PROVIDER=ollama`, otherwise flagged as skipped | Start `ollama serve` or use `LLM_PROVIDER=mock` for offline runs. |

## Span + logging
The command is wrapped with `@span("health.check")`, so the JSON log (`docs/OBSERVABILITY.md`) records each invocation. Exceptions populate `extra.error`.

## CI behavior
- `.github/workflows/smoke.yml` runs the command with `LLM_PROVIDER=mock` to avoid network dependencies.
- Locally, run the health check before `python -m app.cli pipe ...` for faster diagnostics.
<!-- SECTION:HEALTH:END -->
