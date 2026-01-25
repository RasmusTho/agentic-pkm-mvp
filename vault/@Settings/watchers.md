---
auto_run:
  auto_exec_env: WATCHER_AUTO_EXEC
  auto_exec_default: false
  allowed_actions:
    - promote.evergreen
paths:
  index_outbox: tmp/index-outbox.jsonl
  watcher_tick_log: tmp/watcher_tick.jsonl
  panel_event_log: tmp/index-outbox.jsonl
---
# Watcher Settings

The `auto_run` block controls the safe default for automation. Watcher auto-exec defaults to `false` and requires `WATCHER_AUTO_EXEC=1` to be truthy. Only the listed `allowed_actions` may be executed without manual review.

The `paths` block documents the event log locations (outbox + watcher tick log) that the runtime and diagnostics use.
