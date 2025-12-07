State: SoT v4.10 Reality-MVP (current).
# CLI Reference

Click-based CLI surfaces ingestion, transcription, and health checks via `python -m app.cli`.

<!-- SECTION:CLI:BEGIN -->
## Commands
| Command | Description | Key flags |
| --- | --- | --- |
| `health` | Local dependency checks (ffmpeg, yt-dlp, Ollama, outbox path). | `--json`, `--trace-id` |
| `ask QUESTION` | Orchestrated ASK via planner/orchestrator pipeline (mock LLM default). | `--vault-root`, `--enable-mcp-vault` |
| `normalize SOURCE` | Materialize file/URL and run the normalizer agent. | `--json`, `--trace-id` |
| `classify OBJECT_ID` | Classify a previously normalized object. | `--json`, `--trace-id` |
| `transcribe SOURCE` | yt-dlp → ffmpeg → mock/real ASR (URL or file). | `--json`, `--trace-id` |
| `pipe SOURCE` | normalize → classify (auto-transcribe for audio candidates). | `--json`, `--trace-id` |
| `ingest-vault-root` | Non-recursive ingest of vault root (for quick smoke). | `--root`, `--limit` |
| `pkm-alpha-ingest` | Convenience wrapper for ingesting the PKM-Alpha vault root. | `--limit` |
| `vault-alpha-ingest` | Ingest Concepts (+ optional test note) with panel stripping + mirrors. | `--vault-root`, `--max-notes`, `--include-test-note`, `--force` |
| `alpha-human-flows` | Runs flows A–F for demo/regression (ingest + panel + promotion + ASK). | `--vault-root`, `--sample-size`, `--reset-outbox`, `--dry-run` |
| `yggdrasil-init` | Create a Yggdrasil folder skeleton (Mimer/Hugin/Munin/…). | `--root` |
| `llm-trace-flows` | Inspect recent LLM traces grouped by `trace_id`. | `--agent`, `--limit` |

## Commands → Human Flows

| Command | Human Flow | Description |
| --- | --- | --- |
| `python -m app.cli vault-alpha-ingest` | Capture & Ingest | Ingest vault notes safely (UUID healing + mirror updates) |
| `python -m app.cli ask` | ASK | Orchestrated ASK over hybrid retrieval (mock LLM by default) |
| `python -m app.cli alpha-human-flows` | Demo / regression | Walkthrough of ingest → panel → promotion → ASK |

See `docs/HUMAN-FLOWS.md` for flow semantics and `docs/SYSTEM_DESIGN_v4.10.md` for how the CLI fits into the surfaces/topology.

## Examples
```bash
# Normalize a file and return the object_id
python -m app.cli normalize notes/idea.md --json

# Transcribe a YouTube clip with an explicit trace id
python -m app.cli transcribe https://youtu.be/ID --json --trace-id yt123

# Run the full pipeline with optional auto-transcribe
python -m app.cli pipe notes/meeting.md

# Health check before a release
LLM_PROVIDER=mock python -m app.cli health --json

# Ingest vault notes (Concepts)
python -m app.cli vault-alpha-ingest --max-notes 200

# Ask a question through the orchestrator
python -m app.cli ask "What does Reality-MVP focus on?"
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
- For deterministic runs (tests/CI), set `LLM_PROVIDER=mock` and `STORE_BACKEND=memory`.
<!-- SECTION:CLI:END -->
