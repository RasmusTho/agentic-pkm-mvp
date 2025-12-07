State: SoT v4.10 (current; details may lag ARCHITECTURE).
# CLI Reference

Click-based CLI surfaces ingestion, transcription, and health checks via `python -m app.cli`.

<!-- SECTION:CLI:BEGIN -->
## Commands
| Command | Description | Key flags |
| --- | --- | --- |
| `normalize SOURCE` | Materialize file/URL and run the normalizer agent. | `--json`, `--trace-id`. |
| `classify OBJECT_ID` | Classify a previously normalized object. | `--json`, `--trace-id`. |
| `transcribe SOURCE` | yt-dlp → ffmpeg → faster-whisper (URL or file). | `--json`, `--trace-id`. |
| `pipe SOURCE` | normalize → classify (auto-transcribe for audio candidates). | `--json`, `--trace-id`. |
| `health` | Local dependency checks. | `--json`, `--trace-id`. |

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
