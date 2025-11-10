# Dependencies

Översikt över verktyg och bibliotek som krävs i olika miljöer.

<!-- SECTION:DEPENDENCIES:BEGIN -->
## Systemberoenden
| Komponent | Varför | Installationshint |
| --- | --- | --- |
| Python ≥ 3.12 | Primär runtime för CLI/agents. | `pyenv install 3.12.6`, `python -m venv .venv`. |
| ffmpeg | Konverterar ljud till 16 kHz wav (`app/media/transcribe.py:47-65`). | `brew install ffmpeg` / `apt-get install ffmpeg`. |
| yt-dlp | Hämtar YouTube/ljudkällor (`app/media/transcribe.py:22-39`). | `pip install -r requirements.txt` ger rätt version. |
| faster-whisper | Lokalt ASR. | Installeras via pip; kräver C++ build chain om GPU. |
| Ollama | LLM + embeddings (`app/agents/qa/agent.py`, `app/llm/embeddings.py`). | `brew install ollama && ollama serve`. |
| mmdc (valfritt) | Export av Mermaid-diagram (docs/DIAGRAMS.md). | `npm install -g @mermaid-js/mermaid-cli`. |

## Pythonpaket (urval)
- `httpx`, `requests` – alla nätanrop (Ollama/OpenAI/DeepSeek).
- `yt-dlp`, `faster-whisper`, `numpy`, `rank-bm25`, `rapidfuzz` – ingestion, ASR, retrieval.
- `click` – CLI (app/cli).
- `pytest`, `ruff`, `mypy` – dev/test.

## Konfigurationsmatris
| Miljö | Env-setup | Beroenden | Kommentar |
| --- | --- | --- | --- |
| Lokal dev | `LLM_PROVIDER=mock` (eller `ollama` om server finns), `STORE_BACKEND=memory`, `INDEX_OUTBOX_PATH=./tmp/index-outbox.jsonl` | Python venv, yt-dlp, ffmpeg. Ollama valfri. | Health CLI hjälper att verifiera ffmpeg/yt-dlp/outbox. |
| CI smoke (`.github/workflows/smoke.yml`) | `LLM_PROVIDER=mock`, `STORE_BACKEND=memory`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | Installerar ffmpeg via apt, pip installerar allt inkl. yt-dlp. | Ingen Ollama; health-check körs i mock-läge. |
| “Prod” workstation | `LLM_PROVIDER=ollama`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `INDEX_OUTBOX_PATH` pekar mot persistens (t.ex. `~/logs/index-outbox.jsonl`) | Samma som lokal + Ollama server + Postgres (om `STORE_BACKEND=pg`). | Lägg till logrotation/backups för `INDEX_OUTBOX_PATH`. Se docs/OPERATIONS.md. |

## YouTube-transkript och anti-bot
- yt-dlp kan blockeras av YouTube (403/429). Health CLI visar endast importstatus – kör `yt-dlp https://youtu.be/...` manuellt om du behöver felsöka.
- Alternativ: ange `https://piped.video/watch?v=...` eller använd lokalt cachad `.m4a` och kör `python -m app.cli transcribe path/to/audio.m4a`.
- För inloggade cookies kan yt-dlp läsa `~/.config/yt-dlp/cookies.txt`.
- Fallback: lägg ljudfilen i `tmp/audio/` och pekar CLI dit; transcribe steget hoppar över yt-dlp.

## Länkar
- Se `docs/INVENTORY.md` för full lista (env, spans, externa verktyg).
- `docs/OPERATIONS.md` beskriver runbooks och SLO-kopplingar.
<!-- SECTION:DEPENDENCIES:END -->
