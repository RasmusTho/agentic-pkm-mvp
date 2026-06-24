State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Practical dependency matrix for current code paths and environments; code and lockfiles remain the executable source of truth.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Dependencies

Overview of tools and libraries required in each environment.

<!-- dependency source-of-truth -->
## Dependency Source of Truth

`pyproject.toml` is the canonical source of truth for all runtime dependencies (`[project].dependencies`).
Lower-bound version constraints are declared there; upper-bound constraints are added only when breakage
is known or expected (e.g. major-version API breaks).

`requirements.txt` is a **pinned lockfile** — exact versions produced by `pip-compile` or equivalent —
used for reproducible installs in CI and production. It is **not** the authoritative list of required
packages; that list lives in `pyproject.toml`. Do not add new runtime dependencies only to
`requirements.txt` without a matching entry in `[project].dependencies`.

Optional / dev-only packages (testing, linting, type-checking, browser automation) live in
`[project.optional-dependencies]` and are not pinned in `requirements.txt`.

<!-- SECTION:DEPENDENCIES:BEGIN -->
## System dependencies
| Component | Purpose | Installation hint |
| --- | --- | --- |
| Python ≥ 3.12 | Primary runtime for CLI/agents. | `pyenv install 3.12.6`, `python -m venv .venv`. |
| ffmpeg | Converts audio to 16 kHz wav (`app/media/transcribe.py`). | `brew install ffmpeg` / `apt-get install ffmpeg`. |
| yt-dlp | Downloads YouTube/audio sources (`app/media/transcribe.py`). | `pip install -r requirements.txt`. |
| faster-whisper | Local ASR. | Install via pip; GPU builds need a C++ toolchain. |
| Ollama | LLM + embeddings (`app/llm/adapter.py`, `app/llm/embeddings.py`). | `brew install ollama && ollama serve`. |
| mmdc (optional) | Mermaid export for archived/current diagram sources. | `npm install -g @mermaid-js/mermaid-cli`. |

## Python packages (selection)
- `httpx`, `requests` – all network calls (Ollama / OpenAI / DeepSeek).
- `yt-dlp`, `faster-whisper`, `numpy`, `rank-bm25`, `rapidfuzz` – ingestion, ASR, retrieval.
- `click` – CLI (`app/cli`).
- `pytest`, `ruff`, `mypy` – development/test.

## Configuration matrix
| Environment | Env setup | Dependencies | Notes |
| --- | --- | --- | --- |
| Local dev | `LLM_PROVIDER=mock` (or `ollama`), `STORE_BACKEND=memory`, `INDEX_OUTBOX_PATH=./tmp/index-outbox.jsonl` | Python venv, yt-dlp, ffmpeg, optional Ollama. | Health CLI proves ffmpeg/yt-dlp/outbox readiness; JSONL is audit only. |
| CI smoke (`.github/workflows/smoke.yml`) | `LLM_PROVIDER=mock`, `STORE_BACKEND=memory`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | Installs ffmpeg via apt, pip installs requirements. | No Ollama; health runs in mock mode. |
| “Prod” workstation | `LLM_PROVIDER=ollama`, `OLLAMA_HOST`, `LLM_MODEL`, `DATABASE_URL`, `STORE_BACKEND=pg`, `INDEX_OUTBOX_PATH` on persistent storage (e.g. `~/logs/index-outbox.jsonl`) | Same as local + Ollama daemon + Postgres when `STORE_BACKEND=pg`. | DB outbox is canonical in runtime; JSONL is audit-only. Add log rotation/backups for `INDEX_OUTBOX_PATH` (see `docs/OPERATIONS.md`). |

## YouTube transcripts and anti-bot notes
- yt-dlp may be rate limited (403/429). Health only checks imports—run `yt-dlp https://youtu.be/...` manually when debugging.
- Alternative endpoints: `https://piped.video/watch?v=...` or run transcription on a cached `.m4a`.
- For authenticated downloads, yt-dlp reads `~/.config/yt-dlp/cookies.txt`.
- Fallback: place the audio file under `tmp/audio/` and point the CLI to that path; the transcribe step will skip yt-dlp.

## Links
- `docs/INVENTORY.md` for the full variable/span/tool matrix.
- `docs/OPERATIONS.md` for runbooks and SLO context.

## Python Version Policy

- Repo minimum: Python `>=3.12`
  - enforced by `pyproject.toml`
- Repo default and primary validated runtime: Python `3.12`
  - pinned locally via `.python-version`
- CI smoke floor: Python `3.12`
  - used as the compatibility floor for baseline validation
- Forward-compatibility target: Python `3.13`
  - validated in a non-blocking nightly canary lane before raising the floor
- Unsupported baseline targets: Python `3.11` and below
  - do not keep code, typing, or CI pinned to pre-3.12 behavior unless a documented external deployment constraint requires it

Guardrails:
- keep core code compatible with 3.12
- prefer language features and library versions that are clean on 3.12 and 3.13
- raise the minimum only when CI, packaging, and local bootstrap are updated together
- use the optional scripts below when validating compatibility explicitly:
  - `scripts/py312_compile_check.sh`
  - `scripts/py312_smoke_test.sh`
<!-- SECTION:DEPENDENCIES:END -->
