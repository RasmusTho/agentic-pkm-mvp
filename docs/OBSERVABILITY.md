State: SoT v5.5 Reality-MVP baseline locked with the forward line now tracking v5.6. This document defines runtime observability signals and how to interpret them.
# Observability
This document is the runtime observability contract for logs, counters, heartbeats, and status interpretation.

Reading note:
- observability surfaces describe how the current runtime is monitored,
- not the full target-state architecture,
- and not a claim that counters or event paths alone define the system design.

For adjacent operational surfaces:
- use `docs/OPERATIONS.md` as the top-level operations playbook
- use `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md` for incident triage with specific commands and signal interpretation
- use `docs/HEALTH.md` for health CLI behavior and contract details
- use `docs/INFRASTRUCTURE.md` for local Prometheus/Grafana setup
- use `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md` for the current incident-triage workflow across watcher, panel, and CLI-first orchestrator surfaces

## Shared heartbeat/outbox paths
- The health CLI and API rely on `tmp/watcher_heartbeat.json` and `tmp/worker_heartbeat.json` for liveness, plus `INDEX_OUTBOX_PATH` as the audit log.
- The DB outbox (DATABASE_URL/DB_DSN) is the authoritative worker queue; JSONL remains audit/telemetry only.
- If you point a watcher or worker at a different vault or temporary directory, make sure heartbeat paths and `INDEX_OUTBOX_PATH` reference the shared location so health checks see live signals.

## Heartbeat locations and freshness
- Watcher heartbeat default: `tmp/watcher_heartbeat.json` (override with `WATCHER_HEARTBEAT_PATH`).
- Worker heartbeat default: `tmp/worker_heartbeat.json` (override with `WORKER_HEARTBEAT_PATH`).
- Freshness thresholds: `WATCHER_HEARTBEAT_STALE_SECONDS` / `WORKER_HEARTBEAT_STALE_SECONDS` (defaults: 60s).
- Heartbeats with malformed JSON or future timestamps are treated as invalid and surface `status` values like `malformed`/`future`.

Tests: `tests/api/test_health_failures.py::test_health_handles_malformed_heartbeat_json`, `tests/api/test_health_failures.py::test_health_handles_future_heartbeat_timestamp`


Logs are the primary tracing surface; no external APM is required for the current MVP.

## Incident-triage contract
- `docs/OPERATIONS.md` remains the top-level operator routing surface.
- `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md` is the canonical current-state incident workflow for watcher failures, panel runtime / panel intent failures, and CLI-first orchestrator failures.
- Use `trace_id` only where the current runtime actually emits it in logs, events, or audit rows; do not infer planned A2A routing from the presence of trace-oriented fields.

## Alpha Compose Runtime
- Canonical compose stack: `db`, `api`, `watcher`, `worker` (registry watcher).
- The watcher writes audit JSONL events and enqueues DB outbox events; the worker consumes the DB outbox for ingest and promotion side effects.
- Treat `events_log` as append-only audit and `worker_queue` as the live queue; do not derive pending across them unless `worker_queue.mode` is `file`/`jsonl` and explicitly wired.
- Retry/poison-message posture is current-state and bounded: transient missing or unstable note
  failures are requeued with retry metadata, duplicate `event_id` values are skipped, and exhausted
  or failed retry enqueue paths are observable through worker logs plus undelivered DB outbox rows.
  The active runtime does not claim a dedicated DLQ service.

Architectural reading note:
- these monitoring and queue interpretations are current operational truth,
- but they should not be mistaken for the higher-level separation between interaction, cognition, execution, memory, and governance.

## Status snapshot (CLI)
- `app.observability.status_service.get_system_status()` aggregates per-plane object counts (vault vs external), ingest run timestamps/error counts (via ingest summaries), and ASK query counts/latency/error counts over the last 24h window.
- The `python -m app.cli status` (or `poetry run app status`) command renders the snapshot for humans; the interim GUI (root `/` in the FastAPI app) reuses the same backend and surfaces a basic ASK form.
- Status snapshot now reports SoT baseline (v5.5) and forward line (v5.6) plus the active feature list.
- Intent counters: totals and 24h window for `promote.intent.created`, sourced from the configured outbox path; useful for UAT to confirm panel emission without tailing logs.
- **Status semantics**: `events_log` is an append-only audit log (JSONL). `worker_queue` is the active processing queue. Do not derive `pending` across them unless `worker_queue.mode` is `file`/`jsonl` and the queue is explicitly wired to that log.
- **View freshness**: `view_freshness` classifies the current runtime view as `fresh`, `stale`,
  `partial`, or `unknown` from existing ingest, store, and worker-queue signals. This is an
  operator-facing honesty signal for stale or partial runtime views; it is not distributed
  consensus, replica conflict resolution, or a guarantee that every retrieval result is globally
  fresh.
- **`context_dimensions`** (optional): present when a separated-dimension context is active;
  contains `scope`, `sphere_memberships`, and `situated_identity` with SSI-01 canonical semantics.
  Omitted entirely when no separated-dimension context is active — a block of all-null values is
  not permitted. See `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md` (SSI-03) for field semantics and guardrail notes.

## Feature-line and Event Counters
- **SoT baseline vs forward line**: `sot_baseline_version` is the locked baseline (v5.5). `sot_forward_line_version` / `feature_line_version` represent the active forward line (v5.6: LangGraph/Reasoning rollouts on top of the v5.5 baseline). `active_features` enumerates which forward-line capabilities are present (PanelAgent runtime, watcher snapshot/policy track, config-driven panel wiring).
- **Counters surfaced** (total + 24h window):
  - `promotion_executed`: `promote.done` events emitted by the promotion consumer (intent applied).
  - `watcher_runs`: `watcher.run` audit events emitted by both the registry watcher (`watcher run`) and the legacy snapshot watcher (`vault-watcher-run`); registry watcher health still also reports through heartbeat + tick logs.
  - `panel_runs`: `panel.intent.executed` events (panel runtime actually ran).
  - `promote.intent.created`: promotion intents emitted by panel runtime or orchestrator/panel plans.
  - `ingest_runs_by_plane`: count of ingest runs per plane (vault/external) based on last-run metadata.
- **What should increase when running watcher ticks**:
- Intent vs Done: `promote.intent.created` shows the panel emitted an intent; `promotion_executed` (promote.done) shows the consumer applied it. Legacy runtime-loop flows run both when enabled.
  - Registry watcher (`watcher run`): watcher_runs increases; emit-only ticks surface `panel_skipped_auto_exec` against candidate notes; heartbeat/tick logs and `watcher.run` audit rows should agree on recent activity.
  - Legacy snapshot watcher (`vault-watcher-run` or runtime-loop): watcher_runs increases; dry-run still emits `watcher.run`, but ingest/panel/promotion counters should not move because execution short-circuits before side effects.
  - Real run: watcher_runs increases; ingest plane counts increase when changed notes are ingested; panel_runs increases when policy allows panels to run; `promote.intent.created` increases when mapped promotion actions fire.
- `watcher.run` payload: `{changed, ingest_attempted, ingested, panel_candidates, panel_runs, panel_promotions, panel_skipped_policy, panel_skipped_limit, panel_skipped_auto_exec, panel_skipped_allowed_actions, skipped_dedup, skipped_idempotent, skipped_writes_blocked, errors, dry_run, limit_exceeded, snapshot_path, vault_root}` plus envelope (`event_id`, `trace_id`, `timestamp`, `version`, `source.component=watcher`, `source.trigger=registry:<watcher_name>|vault_watcher_run`, `source.sot=v5.6`). Registry watcher `snapshot_path` is empty because it does not use a snapshot file. The CLI fails fast if `INDEX_OUTBOX_PATH`/`--outbox-path` is empty or points to a directory.
- **Common interpretations**:
  - Counters increase but the note is unchanged: an intent was emitted (e.g., `promote.intent.created`), but a consumer (Promotion Agent/worker) must run to mutate files.
  - `changed > 0` but `panel_runs = 0`: panel auto-run policy blocked execution or the run was `--dry-run` / max-notes guard triggered.
  - `ingest_attempted > 0` but `ingested = 0`: ingest errors occurred; check status errors and watcher summary.
  - Watcher runs remain 0: verify `INDEX_OUTBOX_PATH`, vault paths, and snapshot path are writable.

## Observability-as-tests
- Gates: `watcher_runs`, `panel_runs`, `promote.intent.created`, `promotion_executed`, and status error counts double as fitness gates in CI/UAT; runs fail if expected counters do not move or if re-runs create duplicate intents.
- Event chain (current watcher surfaces): each registry or legacy watcher tick emits `watcher.run` with payload fields above; registry watcher ticks also update heartbeat + tick logs and may emit `panel.scan.requested` / `ingest.vault.changed`; panel runs must emit `panel.intent.executed`; promotion consumer must emit `promote.done` (or `promote.error` with reason) when intents exist.
- Latency budget (legacy snapshot watcher): runtime-loop tick (watcher→ingest→panel→promotion) should keep p95 end-to-end latency within a few seconds on the memory backend; outliers must be investigated and recorded in spans.

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
