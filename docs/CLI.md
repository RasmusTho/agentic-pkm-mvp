State: SoT v5.5 baseline (descriptive, partial). The CLI evolves quickly; prefer `python -m app.cli --help` for the authoritative command list.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# CLI Reference

Click-based CLI surfaces ingest, watcher/runtime loop controls, settings tools, and diagnostics via `python -m app.cli`.

Authoritative discovery:
- `python -m app.cli --help`
- `python -m app.cli <command> --help`

<!-- SECTION:CLI:BEGIN -->
## Common Commands (Stable Workflows)
| Command | Description |
| --- | --- |
| `health` | Local dependency checks (ffmpeg/yt-dlp/outbox/LLM reachability). |
| `smoke` | Quick repo smoke tests / checks (CI-oriented). |
| `watcher daemon` | Run the registry watcher daemon (scope, debounce, guardrails). |
| `runtime-loop` | Run watcher→panel→promotion loop once or continuously (operator entrypoint). |
| `settings-validate` | Validate settings artifacts and compiled settings. |
| `settings-explain` | Explain settings provenance / resolution. |
| `llm check` | Probe LLM/embedding endpoint reachability. |

## Commands → Human Flows

| Command | Human Flow | Description |
| --- | --- | --- |
| `python -m app.cli runtime-loop` | Runtime Loop | Watcher tick → panel parse → promotion consumer (opt-in). |
| `python -m app.cli watcher daemon` | Watcher | Continuous vault scan inside scope with guardrails. |
| `python -m app.cli ask` | ASK | Ask questions via the orchestrator pipeline. |

See `docs/HUMAN-FLOWS.md` for flow semantics and `docs/OPERATIONS.md` for operator runbooks.

## Examples
```bash
# Health check before a run
LLM_PROVIDER=mock python -m app.cli health --json

# Run the runtime loop once (operator entrypoint)
python -m app.cli runtime-loop --once

# Run watcher daemon (scan + emit)
python -m app.cli watcher daemon

# Normalize a file and return the object_id (legacy-ish utility; still supported)
python -m app.cli normalize notes/idea.md --json

# Transcribe a YouTube clip with an explicit trace id
python -m app.cli transcribe https://youtu.be/ID --json --trace-id yt123

# Run the full pipeline with optional auto-transcribe
python -m app.cli pipe notes/meeting.md

# Inspect settings provenance
python -m app.cli settings-explain --json
```

## Exit codes
- `0` – all good.
- `1` – validation/exception (yt-dlp / ffmpeg failure, Ollama unavailable, etc.).
- `2` – explicit CLI errors (missing file in `app/cli.py`, `click.BadParameter`, etc.).
- `130` – Ctrl+C propagated by Click. 

## Tips
- Set `PYTHONPATH="$(pwd)"` to ensure local modules resolve.
- `--trace-id` makes it easy to correlate CLI output with logs (`docs/OBSERVABILITY.md`).
- When `pipe` runs on audio URLs the transcribe step covers both CLI output and outbox write—no extra commands required.
<!-- SECTION:CLI:END -->
