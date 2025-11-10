# CLI Reference

Click-baserad CLI levererar ingestion, transcribe och hälso-checker via `python -m app.cli`.

<!-- SECTION:CLI:BEGIN -->
## Kommandon
| Command | Beskrivning | Viktiga flaggor |
| --- | --- | --- |
| `normalize SOURCE` | Materialiserar fil/URL och kör normalizer-agenten. | `--json`, `--trace-id`. |
| `classify OBJECT_ID` | Klassificerar tidigare normaliserat objekt. | `--json`, `--trace-id`. |
| `transcribe SOURCE` | Hämtar ljud (URL/fil) och kör yt-dlp → ffmpeg → faster-whisper. | `--json`, `--trace-id`. |
| `pipe SOURCE` | Kör normalize → classify (och transcribe om ljudkandidat). | `--json`, `--trace-id`. |
| `health` | Kör lokala beroende-checks. | `--json`, `--trace-id`. |

## Exempel
```bash
# Normalisera fil och få object_id
python -m app.cli normalize notes/idea.md --json

# Transkribera YouTube-klipp med explicit trace-id
python -m app.cli transcribe https://youtu.be/ID --json --trace-id yt123

# Pipeline inklusive auto-transcribe
python -m app.cli pipe notes/meeting.md

# Health-check innan release
LLM_PROVIDER=mock python -m app.cli health --json
```

## Exit codes
- `0` – all good.
- `1` – valideringsfel/exception (t.ex. yt-dlp/ffmpeg fel, Ollama otillgänglig).
- `2` – explicita CLI-fel (saknad fil i `app/cli.py` fallback eller `click.BadParameter`).
- `130` – Ctrl+C (propageras från `click`). 

## Tips
- Sätt `PYTHONPATH="$(pwd)"` för att säkerställa att lokala moduler hittas.
- `--trace-id` hjälper när du vill matcha CLI-output med loggar (`docs/OBSERVABILITY.md`).
- När du kör `pipe` på ljud-URLer sker transcribe både för CLI-responsen och outbox-skrivning – inga extra kommandon behövs.
<!-- SECTION:CLI:END -->
