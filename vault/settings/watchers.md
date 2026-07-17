---
auto_run:
  auto_exec_env: WATCHER_AUTO_EXEC
  auto_exec_default: true
  allowed_actions:
    - promote.evergreen
paths:
  index_outbox: tmp/index-outbox.jsonl
  watcher_tick_log: tmp/watcher_tick.jsonl
  watcher_heartbeat: tmp/watcher_heartbeat.json
  worker_heartbeat: tmp/worker_heartbeat.json
  watcher_state: tmp/watcher_state.json
  watcher_stop_file: tmp/WATCHER_STOP
  panel_event_log: tmp/index-outbox.jsonl
---
# Watcher Settings

The `auto_run` block controls the automation default. Watcher auto-exec defaults to `true`; set `WATCHER_AUTO_EXEC=0` for emit-only mode. Only the listed `allowed_actions` may be executed without manual review.

The `paths` block documents the event log locations (outbox + watcher tick log) that the runtime and diagnostics use.
