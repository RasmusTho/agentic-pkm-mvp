# Health CLI

Snabb kontroll att lokala beroenden finns innan ingestion/agent-pipelinen körs.

<!-- SECTION:HEALTH:BEGIN -->
## Körning
```bash
python -m app.cli health --json
```
- Returnerar `{"ok": bool, "checks": {...}, "trace_id": "..."}`.
- Exit-code `0` när alla checks är gröna, annars `1`.
- `--trace-id TRACE123` kan användas för att koppla loggar till andra kommando-körningar.

## Checks
| Nyckel | Källa | Vad kontrolleras | Felåtgärd |
| --- | --- | --- | --- |
| `ffmpeg` | `app/cli/health.py:20-28` | `shutil.which("ffmpeg")` | Installera via paketmanager (`brew install ffmpeg` eller apt). |
| `yt_dlp` | `app/cli/health.py:30-36` | Import och modul-initialisering | Kör `pip install -r requirements.txt`. |
| `index_outbox` | `app/cli/health.py:38-46` | Skrivbarhet för `INDEX_OUTBOX_PATH` (skapar kataloger vid behov) | Justera env eller filrättigheter. |
| `ollama` | `app/cli/health.py:48-49` | GET `${OLLAMA_URL}/api/tags` när `LLM_PROVIDER=ollama`, annars markeras som `skipped` | Starta `ollama serve` eller sätt `LLM_PROVIDER=mock` för offlinekörning. |

## Span och loggning
Kommandot är dekorerat med `@span("health.check")`, vilket gör att resultatet syns i JSON-loggen (`docs/OBSERVABILITY.md`). Vid exception skrivs orsaken i `extra.error`.

## Tolkning i CI
- Workflown `.github/workflows/smoke.yml` kör kommandot med `LLM_PROVIDER=mock` för att undvika nätberoende.
- Lokalt rekommenderas att köra health innan `python -m app.cli pipe ...` för att få snabbare fel-feedback.
<!-- SECTION:HEALTH:END -->
