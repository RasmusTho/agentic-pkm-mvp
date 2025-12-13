State: SoT v4.10 Reality-MVP (current core).
# Observability

Logs are the primary tracing surface; no external APM is required for the current MVP.

## Status snapshot (CLI)
- `app.observability.status_service.get_system_status()` aggregates per-plane object counts (vault vs external), ingest run timestamps/error counts (via ingest summaries), and ASK query counts/latency/error counts over the last 24h window.
- The `python -m app.cli status` (or `poetry run app status`) command renders the snapshot for humans; the interim GUI (root `/` in the FastAPI app) reuses the same backend and surfaces a basic ASK form.
- Status snapshot now reports SoT baseline (v4.10) and forward line (v5.x) plus the active feature list.
- Intent counters: totals and 24h window for `promote.intent.created`, sourced from the configured outbox path; useful for UAT to confirm panel emission without tailing logs.

## Feature-line + Event Counters
- **SoT baseline vs forward line**: `sot_baseline_version` remains the locked Reality-MVP (v4.10). `sot_forward_line_version`/`feature_line_version` represent the active forward line (currently v5.x: PanelAgent + Watchers). `active_features` enumerates which forward-line capabilities are present (PanelAgent runtime, watcher snapshot/policy track, config-driven panel wiring).
- **Counters surfaced** (total + 24h window):
  - `watcher_runs`: watcher tick completions (`watcher.run`/`watcher.run.completed`).
  - `panel_runs`: `panel.intent.executed` events (panel runtime actually ran).
  - `promote.intent.created`: promotion intents emitted by panel runtime or orchestrator/panel plans.
  - `ingest_runs_by_plane`: count of ingest runs per plane (vault/external) based on last-run metadata.
- **How counters should move during watcher runs**:
  - Running `vault-watcher-run` increments watcher runs; if changed notes are ingested, ingest plane counts increase; if panels are allowed and run, panel runs increase; if promotion actions are mapped, `promote.intent.created` increments.
- **Troubleshooting**:
  - Counters moved but the note was not updated: promotion intent is emitted, but a promotion consumer is required to mutate notes/files; ensure the Promotion Agent/consumer is running.
  - Panel runs stay at 0: check panel auto-run policy (frontmatter) and wiring/decider settings; dry-run or max-notes guards may have short-circuited execution.
  - Watcher runs stay at 0: confirm INDEX_OUTBOX_PATH and vault paths are correct; ensure snapshot path is writable.

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
| `status` | "ok" \| "error" | Auto-set, with `extra.error` populated on exceptions. |

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
