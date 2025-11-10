# Dependencies

Overview of tools and libraries required in each environment.

<!-- SECTION:DEPENDENCIES:BEGIN -->
## System dependencies
| Component | Purpose | Installation hint |
| --- | --- | --- |
| Python ≥ 3.12 | Primary runtime for CLI/agents. | `pyenv install 3.12.6`, `python -m venv .venv`. |
| ffmpeg | Converts audio to 16 kHz wav (`app/media/transcribe.py:47-65`). | `brew install ffmpeg` / `apt-get install ffmpeg`. |
| yt-dlp | Downloads YouTube/audio sources (`app/media/transcribe.py:22-39`). | `pip install -r requirements.txt`. |
| faster-whisper | Local ASR. | Install via pip; GPU builds need a C++ toolchain. |
| Ollama | LLM + embeddings (`app/agents/qa/agent.py`, `app/llm/embeddings.py`). | `brew install ollama && ollama serve`. |
| mmdc (optional) | Mermaid export (`docs/DIAGRAMS.md`). | `npm install -g @mermaid-js/mermaid-cli`. |

## Python packages (selection)
- `httpx`, `requests` – all network calls (Ollama / OpenAI / DeepSeek).
- `yt-dlp`, `faster-whisper`, `numpy`, `rank-bm25`, `rapidfuzz` – ingestion, ASR, retrieval.
- `click` – CLI (`app/cli`).
- `pytest`, `ruff`, `mypy` – development/test.

## Configuration matrix
| Environment | Env setup | Dependencies | Notes |
| --- | --- | --- | --- |
| Local dev | `LLM_PROVIDER=mock` (or `ollama`), `STORE_BACKEND=memory`, `INDEX_OUTBOX_PATH=./tmp/index-outbox.jsonl` | Python venv, yt-dlp, ffmpeg, optional Ollama. | Health CLI proves ffmpeg/yt-dlp/outbox readiness. |
| CI smoke (`.github/workflows/smoke.yml`) | `LLM_PROVIDER=mock`, `STORE_BACKEND=memory`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | Installs ffmpeg via apt, pip installs requirements. | No Ollama; health runs in mock mode. |
| “Prod” workstation | `LLM_PROVIDER=ollama`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `INDEX_OUTBOX_PATH` on persistent storage (e.g. `~/logs/index-outbox.jsonl`) | Same as local + Ollama daemon + Postgres when `STORE_BACKEND=pg`. | Add log rotation/backups for `INDEX_OUTBOX_PATH` (see `docs/OPERATIONS.md`). |

## YouTube transcripts and anti-bot notes
- yt-dlp may be rate limited (403/429). Health only checks imports—run `yt-dlp https://youtu.be/...` manually when debugging.
- Alternative endpoints: `https://piped.video/watch?v=...` or run transcription on a cached `.m4a`.
- For authenticated downloads, yt-dlp reads `~/.config/yt-dlp/cookies.txt`.
- Fallback: place the audio file under `tmp/audio/` and point the CLI to that path; the transcribe step will skip yt-dlp.

## Links
- `docs/INVENTORY.md` for the full variable/span/tool matrix.
- `docs/OPERATIONS.md` for runbooks and SLO context.
<!-- SECTION:DEPENDENCIES:END -->
