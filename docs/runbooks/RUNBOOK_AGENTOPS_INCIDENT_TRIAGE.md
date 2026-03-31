State: SoT v5.5 Reality-MVP baseline locked with v5.6 forward-line observability hardening. Current-state incident triage only.
# AgentOps Incident Triage

Use this runbook when an operator has already identified an incident on one of the current shipped runtime surfaces and needs a current-state triage path.

Reading note:
- this runbook covers only the shipped/operator-visible watcher, panel, and CLI-first orchestrator paths
- it does not define future A2A routing, planned multi-agent orchestration, or target-state alerting design
- `docs/OPERATIONS.md` remains the top-level entrypoint; start there when the failing surface is still unclear

## Shared first checks
1. Confirm the runtime surface and whether the issue is watcher, panel execution, or orchestrator plan execution.
2. Run the canonical operator checks:
   ```bash
   make verify-runtime
   docker compose exec -T api python -m app.cli health --json
   docker compose exec -T api python -m app.cli settings-explain --json
   docker compose exec -T api python -m app.cli status
   ```
3. Check shared liveness and queue surfaces:
   - watcher heartbeat: `tmp/watcher_heartbeat.json` or `WATCHER_HEARTBEAT_PATH`
   - worker heartbeat: `tmp/worker_heartbeat.json` or `WORKER_HEARTBEAT_PATH`
   - DB outbox freshness and `delivered_at`
   - JSONL audit log at `INDEX_OUTBOX_PATH`
4. Use `trace_id` when it is already present in logs, outbox events, status output, or audit rows to correlate a single failing run across watcher, panel, and orchestrator surfaces.
5. Escalate to `docs/INFRASTRUCTURE.md` if the issue is compose wiring, startup failure, missing mounts, or dependency reachability rather than runtime behavior.

## Watcher failures

Where to look first:
- `python -m app.cli status`
- `python -m app.cli health --json`
- watcher heartbeat file
- watcher tick log referenced by `WATCHER_TICK_LOG_PATH`

Commands and signals to inspect:
```bash
docker compose exec -T api python -m app.cli health --json
docker compose exec -T api python -m app.cli settings-explain --json
docker compose exec -T api python -m app.cli status
docker compose logs --tail=200 watcher
tail -n 20 tmp/watcher_heartbeat.json
tail -n 20 "$(cat tmp/latest_watcher_tick_log 2>/dev/null)"
```

What to interpret:
- stale or malformed watcher heartbeat means the registry watcher is not reporting healthy ticks
- `settings-explain` is the canonical source for auto-exec gate state, allowlist validity, provenance, and write-guard context
- `status` should confirm watcher automation mode, skip counters, and recent skip reasons
- DB outbox should receive fresh watcher-originated rows such as `ingest.vault.changed` or `panel.scan.requested`; JSONL is audit-only

`trace_id` usage:
- registry watcher runtime health is primarily heartbeat + tick-log driven, not `watcher.run`
- when watcher-emitted outbox/audit events include a `trace_id`, use it to correlate the downstream worker or panel path
- if no `trace_id` is surfaced for the failing watcher tick, rely on timestamp, note path, and event topic correlation instead of inventing one

Escalate when:
- heartbeat stays stale after a controlled restart
- tick logs show repeated scan/backoff/stop-file conditions that require environment or vault-scope intervention
- the failure is really a startup/runtime-topology problem covered by `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`

## Panel runtime and panel intent failures

Where to look first:
- `python -m app.cli status`
- `python -m app.cli settings-explain --json`
- DB outbox topics for `panel.intent.*`, `panel.action.*`, and `promote.intent.created`
- worker logs and JSONL audit tail

Commands and signals to inspect:
```bash
docker compose exec -T api python -m app.cli settings-explain --json
docker compose exec -T api python -m app.cli status --json
docker compose logs --tail=200 worker
curl -sS "http://127.0.0.1:18000/api/events/tail?topic=panel.scan.requested&limit=50"
curl -sS "http://127.0.0.1:18000/api/events/tail?topic=panel.intent.executed&limit=50"
tail -n 50 tmp/index-outbox.jsonl
```

What to interpret:
- `settings-explain` plus `status` should agree on auto-exec posture, allowlist validity, `writes_allowed`, and skip counters
- if watcher signals exist but `panel.intent.executed` does not appear, check policy gating, dedup skips, per-note opt-out, and worker-side processing
- `promote.intent.created` proves the panel produced a mutation intent; it does not by itself prove the promotion consumer applied it
- JSONL and `/api/events/tail` are trace/audit aids; runtime processing is still driven by the DB outbox

`trace_id` usage:
- panel and downstream runtime events may carry a shared `trace_id`; use that to group `panel.scan.requested`, `panel.intent.*`, and follow-on promotion/audit records
- if the failure started from a CLI-triggered panel flow, the CLI-generated `trace_id` should be used as the primary correlation key

Escalate when:
- the panel path is blocked by write-guard or settings provenance that does not match operator intent
- the event chain is present but resulting note changes or frontmatter state contradict `docs/HUMAN-FLOWS.md` or `docs/PANEL_AGENT.md`
- promotion/application behavior, rather than panel intent emission, is the real failing surface

## CLI-first orchestrator failures

Where to look first:
- the failing CLI command output
- orchestrator audit records for `orchestrator.step.*` and `mcp.tool.call.*`
- JSON logs carrying the same `trace_id`

Commands and signals to inspect:
```bash
python -m app.cli status --json
tail -n 50 tmp/index-outbox.jsonl
rg -n "orchestrator.step|mcp.tool.call|trace_id" logs tmp
```

What to interpret:
- current orchestrator runtime is CLI-first and audit-oriented; `app/orchestrator/events.py` emits `orchestrator.step.started`, `orchestrator.step.finished`, `orchestrator.step.error`, `mcp.tool.call.started`, and `mcp.tool.call.finished`
- `ORCHESTRATOR_VERSION=v1|v2` selects the implementation; unrecognized values fall back to `v1`
- a step-level error with a stable `plan_id`, `step_id`, and `trace_id` is the primary current-state failure receipt for plan execution
- these audit records are operational traces, not proof of future A2A routing or multi-agent orchestration

`trace_id` usage:
- the orchestrator carries `plan.meta.trace_id` through step start/finish/error audit events
- use that `trace_id` to gather the full plan execution sequence across audit rows and JSON logs
- when MCP-backed tool calls are involved, correlate `mcp.tool.call.*` entries under the same `trace_id` before treating the failure as an orchestrator core bug

Escalate when:
- the plan itself is structurally invalid and needs a planner or contract fix rather than operator recovery
- audit records are missing entirely for a reproducible CLI plan run
- the failure depends on planned V2/A2A behavior that is not part of current shipped reality

## Escalation map
- startup, compose, mounts, dependency reachability: `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`
- go-live posture and rollout gating: `docs/runbooks/RUNBOOK_GO_LIVE.md`
- watcher/panel manual walkthrough on a bounded note set: `docs/runbooks/UAT_PANEL_WATCHER.md`
- signal definitions and interpretation: `docs/OBSERVABILITY.md`
- top-level operator routing and incident handling order: `docs/OPERATIONS.md`
