# Incident Triage Runbook — Watcher, Panel, and CLI-first Orchestrator

State: SoT v5.5 Reality-MVP baseline. This runbook documents operator-visible incident triage for the current runtime path: registry watcher, panel runtime, CLI-first orchestrator, and associated health/status surfaces.

Purpose: Provide operators with a single, coherent triage entry point for diagnosing failures on the shipped, operator-visible surfaces. Each section describes where to look first, which signals to inspect, and when to escalate or file follow-up issues.

## Triage Order (All Surfaces)

**Start here for any runtime incident:**

1. Run `make verify-runtime` to check container health + in-container runtime health/status.
2. Run `docker compose exec -T api python -m app.cli health --json` for readiness/dependency checks.
3. Run `docker compose exec -T api python -m app.cli status` for watcher/worker/outbox snapshot.
4. Run `docker compose exec -T api python -m app.cli settings-explain --json` for watcher gate, allowlist, and provenance state.
5. Check heartbeat freshness:
   - Watcher: `cat tmp/watcher_heartbeat.json` (or `WATCHER_HEARTBEAT_PATH` override).
   - Worker: `cat tmp/worker_heartbeat.json` (or `WORKER_HEARTBEAT_PATH` override).
6. Check DB outbox freshness:
   - `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_type, COUNT(*), MAX(created_at) FROM outbox WHERE created_at > NOW() - INTERVAL '5 minutes' GROUP BY event_type ORDER BY event_type;"`
7. Inspect relevant logs for errors or unusual patterns:
   - `docker compose logs -f watcher` or `docker compose logs -f worker` or `docker compose logs -f api`
8. If the issue is surface-specific (watcher, panel, orchestrator), follow the section below.
9. For topology/startup issues, refer to `docs/INFRASTRUCTURE.md` and `docs/HEALTH.md`.

## Watcher Incidents

### Where to look first

1. **Heartbeat file**:
   ```bash
   cat tmp/watcher_heartbeat.json
   ```
   - Expected fields: `last_tick_at`, `last_tick_duration_ms`, `tick_count`, `status`, `health.pass_fail`.
   - If missing or stale (> 60 seconds old): watcher process crashed or is stuck.
   - If `status` is not `ok`: watcher reported a problem in the last tick.

2. **Tick log**:
   ```bash
   tail -50 tmp/watcher_tick_log.jsonl
   ```
   - Each line is one watcher tick; shows changed counts, ingest attempts, skip reasons, errors.
   - High `ingest_attempted` but low `ingested`: ingest errors; check details in full logs.
   - `panel_candidates > 0` but `panel_runs = 0` and `WATCHER_AUTO_EXEC=1`: panel auto-exec blocked; check `panel_skipped_policy` and `panel_skipped_limit`.

3. **Settings gate**:
   ```bash
   python -m app.cli settings-explain --json | jq '.watcher_auto_exec, .allowlist, .writes_allowed, .panel_skipped_policy'
   ```
   - Verify `watcher_auto_exec` is armed and allowlist is valid before treating auto-run as live.
   - If `writes_allowed = false`: writes are blocked; check safe-mode/write-guard state in the output.

4. **Status snapshot**:
   ```bash
   python -m app.cli status | grep -A 20 "Watcher automation"
   ```
   - Look for `mode` (emit-only vs auto-exec), skip counters, and last-run error summary.

### Commands and signals to inspect

| Signal | Command | What it shows |
| --- | --- | --- |
| Liveness | `tail -1 tmp/watcher_heartbeat.json \| jq '.last_tick_at'` | Last watcher tick timestamp; if > 60s old, process is stale or stuck. |
| Vault paths scanned | `python -m app.cli status \| grep "vault_notes\|vault_path"` | Confirmed vault location and object count; mismatch suggests vault path or permission issue. |
| Ingest errors | `docker compose logs watcher \| grep -i "ingest\|error" \| tail -20` | Errors during note parsing or DB writes; check vault formatting or permissions. |
| Dedup queue | `python -m app.cli status \| grep "dedup"` | `skipped_dedup` counter; high values mean the same note is changing too fast. |
| Trace propagation | `jq 'select(.node=="watcher.*") \| {trace_id, node, status, latency_ms}' logs/trace.jsonl` | Span traces for this tick; correlate by `trace_id` to see ingest/panel timeline. |
| Outbox enqueue | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_type, COUNT(*) FROM outbox WHERE source_component = 'watcher' AND created_at > NOW() - INTERVAL '10 minutes' GROUP BY event_type;"` | Verify `ingest.vault.changed` and `panel.scan.requested` events are enqueued. |

### Common watcher issues

**Issue: Heartbeat stale or missing**
- Watcher process crashed or is blocked.
- Check: `docker compose ps` (ensure `watcher` is running), `docker compose logs watcher | tail -50` (look for crash/exception).
- Recovery: Restart watcher: `docker compose restart watcher`.

**Issue: `changed > 0` but `ingested = 0`**
- Ingest pipeline errored (vault formatting, embed provider unreachable, DB permission issue).
- Check: `docker compose logs watcher | grep -i "ingest\|error"`, `python -m app.cli health --json` (confirm DB/LLM health).
- Recovery: Fix the underlying issue (vault path, DB connection, LLM reachability), then re-run: `python -m app.cli watcher run --max-ticks 1`.

**Issue: `panel_candidates > 0` but `WATCHER_AUTO_EXEC=1` and `panel_runs = 0`**
- Panel auto-exec is blocked by policy or rate limit.
- Check: `python -m app.cli status | grep -A 5 "panel_skipped"` to see skip reasons (policy vs limit).
- Check: `python -m app.cli settings-explain | jq '.panel_skipped_policy, .panel_skipped_limit'` to verify settings.
- Recovery: Confirm settings are correct, then either adjust policy or re-run with `PANEL_PROACTIVE_ASSIST=1` if safe.

**Issue: High dedup skip count**
- Same note is being updated too frequently; watcher dedup guard is preventing duplicate panel runs.
- Check: `python -m app.cli status | jq '.dedup'` for skip counts by reason.
- Investigation: Is the note being edited externally or is iCloud/sync causing re-triggers? Check vault sync behavior.
- Recovery: If spurious, run `watcher run` again; true duplicates are expected behavior.

## Panel Runtime / Intent Incidents

### Where to look first

1. **Status intent counters**:
   ```bash
   python -m app.cli status | grep -A 5 "Intent counters"
   ```
   - `promote.intent.created` (24h): panel emitted intents to be applied.
   - `panel.intent.executed` (24h): panel runtime actually ran.
   - If created > executed: intents are queued but not yet applied; check worker.

2. **Panel logs**:
   ```bash
   docker compose logs -f panel 2>&1 | grep -i "error\|exception" | head -20
   ```
   - If panel is not a separate container, check `docker compose logs api` and filter for `panel.*` spans.

3. **Outbox events**:
   ```bash
   docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_type, COUNT(*), MAX(created_at) FROM outbox WHERE event_type LIKE 'panel.%' AND created_at > NOW() - INTERVAL '30 minutes' GROUP BY event_type ORDER BY MAX(created_at) DESC;"
   ```
   - Expected event chain: `panel.intent.created` → (worker consumes) → `panel.intent.executed` → (consumer emits) → `promote.intent.created` (if mapped).

4. **Trace propagation for a specific panel run**:
   ```bash
   # Find a panel run by tracing its event_id
   docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_id, trace_id, created_at FROM outbox WHERE event_type = 'panel.intent.created' ORDER BY created_at DESC LIMIT 5;"
   # Then correlate logs by trace_id
   jq "select(.trace_id == \"<trace_id>\") | {node, status, latency_ms, extra}" logs/trace.jsonl
   ```

### Commands and signals to inspect

| Signal | Command | What it shows |
| --- | --- | --- |
| Intent creation rate | `python -m app.cli status \| jq '.promote.intent.created'` | Promotion intents created in the last 24h; zero means no panel runs or all were non-promotion. |
| Panel execution rate | `python -m app.cli status \| jq '.panel_runs'` | Panel runtime executions in the last 24h; compare to intent count. |
| Action catalog validity | `python -m app.cli settings-explain --json \| jq '.panel_actions'` | Loaded action catalog (source path, hash, validity); empty or error means invalid catalog. |
| Panel log entries | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT COUNT(*), MAX(created_at) FROM outbox WHERE event_type = 'panel.log.created' AND created_at > NOW() - INTERVAL '1 hour';"` | Panel log emissions; high counts suggest verbose/debug logging. |
| Promotion intent skips | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT COUNT(*), MAX(created_at) FROM outbox WHERE event_type = 'promote.intent.created' AND created_at > NOW() - INTERVAL '1 hour';"` | Promotion intents enqueued for the worker; compare to panel runs. |

### Common panel issues

**Issue: Panel intent created but not executed**
- Worker may be stalled, crashed, or not consuming the DB outbox.
- Check: `python -m app.cli status | jq '.worker_queue'` (is the worker alive?), `docker compose logs worker | tail -50` (check for errors).
- Recovery: Restart worker: `docker compose restart worker`, then check outbox again.

**Issue: Panel intent created but promote intent never emitted**
- Panel ran but did not emit a promotion action (or action was not in the allowlist).
- Check: `python -m app.cli settings-explain | jq '.allowed_actions'` to verify the action is allowlisted.
- Check: `docker compose logs api | grep -i "panel\|promote" | tail -20` to see if the action ran.
- Recovery: Verify the note has the correct AI panel fence and action is allowlisted. Re-run panel: `python -m app.cli panel run-many <uuid>`.

**Issue: Panel action catalog invalid**
- `docs/settings/panel-actions.md` or vault `@Settings/watchers.md` has syntax errors or is unreachable.
- Check: `python -m app.cli settings-validate --json` for parse errors.
- Check: `python -m app.cli settings-explain | jq '.panel_actions.error'` for details.
- Recovery: Fix the YAML/frontmatter syntax in the source, then re-run: `python -m app.cli settings-validate` to confirm.

**Issue: Panel run is very slow**
- Latency spike in embedding, reasoning, or action execution.
- Check: `jq "select(.node | contains(\"panel\")) | {node, latency_ms, status}" logs/trace.jsonl | jq -s 'sort_by(.latency_ms) | reverse | .[0:5]'` for slowest spans.
- Investigation: Is LLM provider slow? Is embedding index hot? Are there resource constraints?
- Recovery: Profile the slow component (LLM, embedding, DB) and address bottleneck.

## CLI-first Orchestrator (Planner → Plan Execution)

### Where to look first

1. **Planner execution status**:
   ```bash
   python -m app.cli status | grep -A 10 "Planner\|Orchestrator" || echo "Not directly surfaced in status; check logs."
   ```
   - Planner and orchestrator emit events to the outbox but may not have a dedicated status line yet.

2. **Orchestrator events**:
   ```bash
   docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_type, COUNT(*), MAX(created_at) FROM outbox WHERE event_type LIKE 'orchestrator.%' OR event_type LIKE 'planner.%' OR event_type LIKE 'plan.%' AND created_at > NOW() - INTERVAL '1 hour' GROUP BY event_type ORDER BY MAX(created_at) DESC;"
   ```
   - Expected events: `plan.created`, `plan.execution.started`, `plan.step.executed`, `plan.execution.completed` (or error variants).

3. **Plan trace ID**:
   ```bash
   # Find a recent plan execution by trace_id
   jq "select(.node | contains(\"plan\")) | {trace_id, node, status, latency_ms}" logs/trace.jsonl | jq -s 'unique_by(.trace_id) | .[-1]'
   ```
   - Correlate all plan-related spans by this trace_id to see the full orchestrator lifecycle.

4. **CLI command logs**:
   ```bash
   docker compose logs api | grep -i "plan\|orchestrate" | tail -50
   ```
   - CLI-driven plan runs emit logs with plan ID, step count, and execution status.

### Commands and signals to inspect

| Signal | Command | What it shows |
| --- | --- | --- |
| Plan creation rate | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT COUNT(*), MAX(created_at) FROM outbox WHERE event_type = 'plan.created' AND created_at > NOW() - INTERVAL '24 hours';"` | Plans created in the last 24h (via planner or operator CLI). |
| Plan execution status | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT event_type, COUNT(*) FROM outbox WHERE event_type LIKE 'plan.execution.%' AND created_at > NOW() - INTERVAL '1 hour' GROUP BY event_type;"` | Breakdown of plan starts, step executions, and completions. |
| Orchestrator version | `python -m app.cli settings-explain --json \| jq '.orchestrator_version'` | Active orchestrator version (v1 or v2); v2 includes parallel scheduling. |
| Step errors | `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT COUNT(*), MAX(created_at) FROM outbox WHERE event_type LIKE 'plan.step.%error%' AND created_at > NOW() - INTERVAL '1 hour';"` | Failed plan steps; high counts suggest action/dependency failures. |
| Trace correlation | `jq "select(.trace_id == \"<plan_trace_id>\") | {node, status, extra}" logs/trace.jsonl \| jq 'select(.status == "error")'` | All error spans for a plan execution; helps identify which step failed. |

### Common orchestrator issues

**Issue: Plan created but never executed**
- Planner may have stalled or the plan was never dispatched to the orchestrator.
- Check: `docker compose logs api | grep -i "plan" | tail -30` for planner errors or execution start logs.
- Check: `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT * FROM outbox WHERE event_type = 'plan.created' ORDER BY created_at DESC LIMIT 3\G"` to see if the plan was created.
- Recovery: If the plan exists but wasn't executed, manually trigger it via CLI: `python -m app.cli ask --plan-id <id>` (exact command depends on current CLI surface).

**Issue: Plan step failed**
- A step within the plan errored; the orchestrator may or may not have continued.
- Check: `docker compose exec -T db psql -U postgres agentic_pkm -c "SELECT * FROM outbox WHERE event_type LIKE 'plan.step.%' AND created_at > NOW() - INTERVAL '30 minutes' ORDER BY created_at DESC LIMIT 10\G"` to see step status.
- Check: `jq "select(.node | contains(\"plan\")) | select(.status == \"error\") | {node, extra}" logs/trace.jsonl | head -5` to see the error details.
- Investigation: Is the step's action allowlisted? Does the action's dependency exist? Is the embedding/retrieval step returning results?
- Recovery: Fix the underlying action or dependency, then replan or resubmit the failing step.

**Issue: Orchestrator V2 slowness or unexpected behavior**
- Orchestrator V2 (parallel scheduling, dependency-aware execution) is active but behaves unexpectedly.
- Check: `python -m app.cli settings-explain | jq '.orchestrator_version'` to confirm v2 is active.
- Check: `docker compose logs api | grep -i "orchestrator\|v2" | tail -30` for v2-specific logs.
- Investigation: Are dependencies correctly specified in the plan? Is parallelism causing resource contention? Does the trace show unexpected step ordering?
- Recovery: If v2 is causing issues, fall back to v1 with `ORCHESTRATOR_VERSION=v1`, then file a follow-up issue with the trace ID and plan details.

## Escalation and Follow-ups

### Escalation paths

| Issue type | Next step | Document |
| --- | --- | --- |
| Watcher stuck or crashing | Restart container; if persistent, check INFRASTRUCTURE.md for DB/vault permissions. | `docs/INFRASTRUCTURE.md`, `docs/HEALTH.md` |
| Panel action not working | Verify action is in allowlist and vault settings are valid. | `docs/settings/panel-actions.md`, `docs/PANEL_AGENT.md` |
| Worker not consuming outbox | Restart worker; if persistent, check DB outbox health and worker permissions. | `docs/INFRASTRUCTURE.md` |
| LLM/embedding provider unreachable | Check reachability from container; verify endpoint config and network routing. | `docs/INFRASTRUCTURE.md`, `docs/LLM.md` |
| Plan execution dependency broken | Check that source artifacts exist and are accessible; replan if needed. | `docs/ARCHITECTURE.md` |
| Trace ID not found in logs | Ensure `trace_id` propagates from CLI entry point; check observability setup. | `docs/OBSERVABILITY.md` |

### When to file an issue

File a follow-up GitHub Issue if:
- A component fails after restart and the error is not covered above.
- Incident is related to a forward-line feature (e.g., Orchestrator V2, LangGraph adoption) and is tagged as `agent:needs-human`.
- A security or data integrity incident occurs (e.g., note corruption, unintended mutation).
- Incident suggests a race condition or concurrency bug that cannot be reproduced locally.

Include in the issue:
- Trace ID(s) from the incident.
- Relevant heartbeat/status snapshots.
- Error logs from `docker compose logs <component>`.
- Whether the issue is reproducible or one-off.
- Whether the component is part of the active baseline or a forward-line feature.

## Related Documents

- **Operator playbook**: `docs/OPERATIONS.md` (top-level triage order, component overview).
- **Observability contract**: `docs/OBSERVABILITY.md` (signal interpretation, span schema, jq recipes).
- **Health semantics**: `docs/HEALTH.md` (readiness checks, degraded-state rules).
- **Infrastructure & startup**: `docs/INFRASTRUCTURE.md` (local stack, Docker Compose, startup troubleshooting).
- **Panel runtime details**: `docs/PANEL_AGENT.md` (panel fence syntax, action semantics).
- **Watcher & registry configuration**: `docs/OPERATIONS.md#watcher-operations` and `configs/watchers.yaml`.
- **UAT walkthrough**: `docs/runbooks/UAT_PANEL_WATCHER.md` (end-to-end validation flow).
