# Observability

Loggarna är primär källa för spårning; inga externa APM:er krävs för MVP.

<!-- SECTION:OBS:BEGIN -->
## JSON-logg och span-schema
`app/obs/log.py:11-58` skriver en rad per span med följande nycklar:
| Fält | Typ | Beskrivning |
| --- | --- | --- |
| `trace_id` | str | Propageras från CLI/agent; slumpas annars. |
| `node` | str | Namn från `@span("...")`, se docs/INVENTORY.md för lista. |
| `latency_ms` | float | Tid för funktionen. |
| `token_in`/`token_out` | int \| null | Valfria värden som kan skickas via `_token_in/out`. |
| `extra` | dict | Fritt payload (felmeddelande, checkstatus m.m.). |
| `status` | `"ok"` \| `"error"` | Sätts automatiskt, `error` inkluderar `extra.error`. |

Exempel (QA-svar):
```json
{
  "trace_id": "cli-qa-1",
  "node": "agent.answer",
  "latency_ms": 842.117,
  "token_in": null,
  "token_out": null,
  "extra": {},
  "status": "ok"
}
```

## jq-recept
- Latens per nod (p95 approximativt):  
  ```bash
  jq -s '[.[] | select(.node=="agent.answer") | .latency_ms] | add/length' logs/trace.jsonl
  ```
- Filtrera på node + status:  
  ```bash
  jq 'select(.node=="transcribe" and .status=="error")' logs/*.jsonl
  ```
- Koppla ihop CLI-run med health-check:  
  ```bash
  jq 'select(.trace_id=="TRACE123") | {node, status, extra}' logs/*.jsonl
  ```

## Spans i praktiken
- `health.check` – loggar resultatet av ffmpeg/yt-dlp/outbox/Ollama-kontroller innan CLI svarar.
- `agent.*` – fyra steg (draft, self_check, finalize, answer) gör det lätt att se flaskhalsar.
- `transcribe` – inkluderar hela kedjan download → ffmpeg → ASR.

## PII och loggar
Se `docs/PRIVACY.md` för vilka fält som måste maskas innan loggar skickas någon annanstans. Guideline: logga aldrig råtext från källan i `extra`, endast statistik (antal ord, segment).
<!-- SECTION:OBS:END -->
