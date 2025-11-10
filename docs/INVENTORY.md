# Runtime Inventory

Samlad lägesbild över konfiguration, beroenden och driftkontrakt. Hålls uppdaterad i samma PR som ändringar i kod eller CI.

<!-- SECTION:INVENTORY:BEGIN -->
## Environment variables
| Variable | Location (file:line) | Default | Effekt |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | app/agents/qa/agent.py:20, app/llm/adapter.py:4 | `ollama` (CLI-scriptet `app/cli.py:24` sätter `mock` lokalt) | Väljer backend för QA-agent, embeddings och CLI; värden: `ollama`, `mock`, `openai`, `deepseek`. |
| `LLM_MOCK_RESPONSE` | app/agents/qa/agent.py:27, app/cli.py:25 | `Mock response [#1]` resp. CLI-default JSON | Svar som returneras när `LLM_PROVIDER=mock`, både i CLI och agentflöden. |
| `LLM_MAX_TOKENS` | app/agents/qa/agent.py:13 | `512` | Begränsar antalet tokens per QA-svar när Ollama används. |
| `LLM_TIMEOUT` | app/agents/qa/agent.py:41, app/llm/embeddings.py:37, app/llm/adapter.py:20 | `120` s för chat, `60` s för embeddings/externa API:er | HTTP-timeout mot Ollama/OpenAI/DeepSeek. |
| `OLLAMA_HOST`/`OLLAMA_URL` | app/agents/qa/agent.py:31, app/llm/embeddings.py:10 | `http://127.0.0.1:11434` | Bas-URL för /api/chat och /api/embeddings. `OLLAMA_URL` vinner över `OLLAMA_HOST`. |
| `OLLAMA_MODEL` | app/agents/qa/agent.py:32 | `llama3.1:8b-instruct` | Standardmodell för QA-agentens /api/chat-anrop. |
| `OLLAMA_EMBED_MODEL` / `EMBED_MODEL` | app/llm/embeddings.py:11 | `nomic-embed-text:latest` | Modell som används av `/api/embeddings`; kan överstyras för specialiserade experiment. |
| `LLM_MODEL` / `LLM_REASONING_MODEL` | app/llm/adapter.py:5-6 | `llama3.1:8b` | Används av klassificeringsagentens generaliserade LLM-adapter. `LLM_REASONING_MODEL` aktiveras när `reasoning=True`. |
| `OPENAI_API_KEY`, `OPENAI_BASE` | app/llm/adapter.py:26-33 | – (krav) / `https://api.openai.com/v1/chat/completions` | Krävs om `LLM_PROVIDER=openai`. |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` | app/llm/adapter.py:38-44 | – (krav) / `https://api.deepseek.com/chat/completions` | Krävs om `LLM_PROVIDER=deepseek`. |
| `LLM_TEMPERATURE` | app/services/llm.py:69 | `0` | Temperatur när `app/services/llm.py` används utanför QA-agenten. |
| `INDEX_OUTBOX_PATH` | app/index/outbox.py:12-20, app/cli.py:76 | `./tmp/index-outbox.jsonl` | Bestämmer filen där ingestion/index-händelser appendas; måste vara skrivbar (se health-check). |
| `STORE_BACKEND` | app/cli.py:21, app/stores/provider.py:39 | `memory` | Styr om ObjectStore kör i minne eller Postgres (`pg`). |
| `DATABASE_URL` | app/memory/store.py:16, app/stores/pg.py:21 | `postgresql+psycopg://app:app@127.0.0.1:15432/app` | DSN för Postgres; används av stores, agenter och tester. |
| `MEMORY_ENABLED` | app/memory/store.py:23 | `true` | Om `false` hoppar minnesstore över writes. |
| `ASR_MODEL`, `ASR_DEVICE` | app/media/transcribe.py:71-72 | `base`, `auto` | Modellnamn och enhet (cpu/cuda) för faster-whisper. |
| `ASR_COMPUTE_TYPE` | – (hårdkodat `int8` i app/media/transcribe.py:75) | `int8` | Ej kopplad till env ännu; noterad som gap. |
| `EVENT_LOG` | app/services/events.py:4 | `events.jsonl` | Bestämmer standardfil för audit/event-loggar. |
| `TRACE_LOG_PATH` | app/observability/trace_log.py:2 | `/tmp/trace.jsonl` | Output-fil när trace-loggning aktiveras. |

## Span nodes (`@span`)
| Node | Location | Funktion | Extra-fält |
| --- | --- | --- | --- |
| `transcribe` | app/media/transcribe.py:122 | Ljudtranskribering inklusive yt-dlp och ffmpeg. | `extra` fylls endast vid fel (t.ex. `CalledProcessError`). |
| `agent.draft` | app/agents/qa/agent.py:59 | Första LLM-svaret med citationskrav. | `_token_in/out` kan sättas av anropare; annars bara status. |
| `agent.self_check` | app/agents/qa/agent.py:82 | Post-draft validering (referenser, längd). | `extra` innehåller felorsak om undantag kastas. |
| `agent.finalize` | app/agents/qa/agent.py:109 | Justering (t.ex. brist på kontext) innan leverans. | Inga extra-fält idag. |
| `agent.answer` | app/agents/qa/agent.py:117 | Full pipeline: retrieval → draft → self-check → finalize. | Läser `hybrid_search` resultat; loggar fel-info om retrieval misslyckas. |
| `health.check` | app/cli/health.py:49 | Kör lokala beroende-checker och returnerar JSON-resultat. | `extra` får automatisk `error`-nyckel vid exception; CLI-output innehåller fulla `checks`. |

## CLI-ytor
Alla kommandon körs via `python -m app.cli <command>` (Click). `--json` flaggan slår över till maskinläsbar output; `--trace-id` kan sättas manuellt.

| Command | Location | Beskrivning | Exit codes |
| --- | --- | --- | --- |
| `normalize SOURCE [--json --trace-id]` | app/cli/__init__.py:34-55 | Materialiserar fil/URL, kör normalizer-agenten och skriver core-object (se app/agents/normalizer/agent.py). | 0 vid success, bubbla upp `FileNotFoundError` → exit 1. |
| `classify OBJECT_ID [--json --trace-id]` | app/cli/__init__.py:57-74 | Realtidsklassificering av ett redan normaliserat objekt via classifier-agenten. | 0 vid success, CLI visar undantag om objekt saknas. |
| `transcribe SOURCE [--json --trace-id]` | app/cli/__init__.py:76-94 | Kör yt-dlp/ffmpeg/faster-whisper och lägger resultat i index-outbox (`kind=transcript`). | 0 vid success, ffmpeg/yt-dlp fel → exit 1. |
| `pipe SOURCE [--json --trace-id]` | app/cli/__init__.py:96-133 | Kedjar normalize → classify (+transcribe för ljud/URL) och skriver pipeline-resultat samt JSONL-rad. | 0 vid success, exit 1/2 vid saknad källa. |
| `health [--json --trace-id]` | app/cli/__init__.py:135-147, app/cli/health.py | Kör lokala kontroller (ffmpeg, yt-dlp, INDEX_OUTBOX_PATH, Ollama reachability) och signalerar fel via exit 1. | 0 när alla checks `ok`; 1 annars. |

## Externa verktyg och nätanrop
- **yt-dlp** – hämtar ljud/m4a från YouTube eller andra URL:er (`app/media/transcribe.py:22-39`).
- **ffmpeg** – konverterar valfritt format till 16 kHz mono wav (`app/media/transcribe.py:47-65`).
- **faster-whisper** – lokalt ASR med modellcache `_MODEL_CACHE` (`app/media/transcribe.py:68-99`).
- **Ollama** – REST-endpoints `/api/chat` och `/api/embeddings` (`app/agents/qa/agent.py:31-48`, `app/llm/embeddings.py:34-43`).
- **HTTPX/requests** – används även mot OpenAI/DeepSeek (`app/llm/adapter.py:16-47`).

## Index-outbox JSONL-schema
Kärnkontraktet hålls i `app/index/outbox.py:28-58`. Varje rad är en JSON med minst:
```json
{
  "object_id": "uuid4",
  "kind": "transcript|note|pipeline",
  "source_ref": "path-or-url",
  "payload": {
    "text": "...",
    "segments": [],
    "language": "sv"
  },
  "embedding": null,
  "topic": null
}
```
Transcribe-posten (app/media/transcribe.py:102-134) får dessutom `trace_id` innan return. `append_jsonl` skriver alltid newline och försöker fan-in text till den in-memory retrieval store:n (`app/retrieval/hybrid.py:28-112`).

## Fel & edge cases
- **YouTube anti-bot (403/429)** – `YoutubeDL.extract_info` höjer `DownloadError`; CLI visar undantag. Kör om med cookies eller pipe-host (se docs/DEPENDENCIES.md). (`app/media/transcribe.py:36-38`)
- **ffmpeg saknas** – `subprocess.run(..., check=True)` kastar `CalledProcessError`; health-check flaggar samma scenario (`app/media/transcribe.py:54-65`, `app/cli/health.py:20-28`).
- **yt-dlp saknas** – Import error redan vid modul-laddning; health-check visar tydligt fel (`app/media/transcribe.py:10-15`, `app/cli/health.py:30-36`).
- **ASR-modell ej installerad** – `faster-whisper` kastar undantag; koden re-raises med tydlig instruktion (`app/media/transcribe.py:68-82`).
- **Ollama nere** – QA-agenten och health CLI rapporterar `requests.ConnectionError`/`httpx` fel med host i meddelandet (`app/agents/qa/agent.py:31-48`, `app/cli/health.py:38-49`).
- **INDEX_OUTBOX_PATH otillgänglig** – `append_jsonl` slår larm och health-check provskriver en rad (`app/index/outbox.py:28-58`, `app/cli/health.py:30-36`).

## Cache-, timeout- och breaker-policy
- `_MODEL_CACHE` (dict) lagrar `(ASR_MODEL, ASR_DEVICE)` → `WhisperModel` (`app/media/transcribe.py:19-76`). Ingen eviktionspolicy; restart krävs för att frigöra minne.
- `_embed_single` är `@lru_cache(maxsize=512)` och återanvänder embeddings per text/provider/modell (`app/llm/embeddings.py:27-43`).
- `LLM_TIMEOUT` styr HTTP-timeouts för Ollama/OpenAI/DeepSeek (60–120 s). Ingen per-call retry; se docs/LLM_BACKENDS.md för gap.
- `CircuitBreaker` och `timeout_wrapper` finns i `app/quality/guardrails.py:32-61` men används främst av agents i `app/agents/promotion`. QA-agenten använder dem inte ännu → dokumenterat som förbättring.
- Logging-spanen registrerar alltid latency i millisekunder och bär `status` (`app/obs/log.py:20-58`), vilket används av `jq`-recepten i docs/OBSERVABILITY.md.
<!-- SECTION:INVENTORY:END -->
