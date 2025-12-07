State: SoT v4.10 Reality-MVP (current core).
# Observability

Logs are the primary tracing surface; no external APM is required for the current MVP.

<!-- SECTION:OBS:BEGIN -->
## JSON log and span schema
`app/obs/log.py:11-58` emits one line per span with:
| Field | Type | Description |
| --- | --- | --- |
| `trace_id` | str | Propagated from the CLI or generated when missing. |
| `node` | str | The `@span("...")` name (see `docs/INVENTORY.md`). |
| `latency_ms` | float | Execution time in milliseconds. |
| `token_in` / `token_out` | int \| null | Optional token counters passed via `_token_in/out`. |
| `extra` | dict | Free-form payload (errors, check status, metadata). |
| `status` | `"ok"` \| `"error"` | Auto-set, with `extra.error` populated on exceptions. |

Example (QA response):
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

## jq recipes
- Latency per node (average):  
  ```bash
  jq -s '[.[] | select(.node=="agent.answer") | .latency_ms] | add/length' logs/trace.jsonl
  ```
- Filter by node + status:  
  ```bash
  jq 'select(.node=="transcribe" and .status=="error")' logs/*.jsonl
  ```
- Correlate a CLI run via `trace_id`:  
  ```bash
  jq 'select(.trace_id=="TRACE123") | {node, status, extra}' logs/*.jsonl
  ```

## Spans in practice
- `health.check` – records ffmpeg / yt-dlp / outbox / Ollama readiness before the CLI exits.
- `agent.*` – four stages (draft, self_check, finalize, answer) expose where time is spent.
- `transcribe` – covers download → ffmpeg → ASR.

## PII considerations
See `docs/PRIVACY.md` for masking guidance. Rule of thumb: never log raw user text in `extra`; only record aggregate stats (word counts, segment counts, etc.).
<!-- SECTION:OBS:END -->
