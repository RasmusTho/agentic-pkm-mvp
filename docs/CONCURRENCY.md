State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Normative concurrency and idempotency guardrails for watcher, worker, and agent-triggered side effects in the current runtime.
# Concurrency & Idempotency Guide

This guide defines the required concurrency and idempotency guards for watcher auto-exec, event consumption, and agent-triggered side effects in the current runtime.

Related docs:
- `docs/EVENTS.md` for canonical event envelope requirements, including `event_id`
- `docs/OPERATIONS.md` for runtime/operator checks when concurrency failures are suspected
- `docs/guardrails.md` for the shorter quality/safety summary

## DedupTaskQueue pattern (MUST)
The system MUST use a DedupTaskQueue for tasks that can be triggered concurrently or retried (watcher runs, panel auto-exec, orchestrator steps).

- **Keying:** every task MUST include a deterministic `dedup_key` (e.g., `watcher.run:<vault_root>:<snapshot_id>` or `panel.exec:<note_uuid>:<panel_id>`).
- **TTL:** keys MUST have a TTL; keys MAY be released early when completion is recorded.
- **Replay:** if a task with the same `dedup_key` is active or completed within TTL, the queue MUST return the existing task id and MUST NOT execute a duplicate task.
- **Completion:** task completion MUST be recorded with a terminal status (success/failed/skipped) so retries can be decisioned deterministically.

## Optimistic locking strategy (MUST)
Writes to notes or objects MUST use optimistic locking with a version token to prevent silent corruption.

- **Version token:** use a version column, content hash, or `mtime` snapshot captured at read time.
- **Mismatch behavior:** on version mismatch, the write MUST fail safe (no overwrite), emit a warning/diagnostic, and surface a retry path.
- **No silent merges:** automatic merges are not allowed unless explicitly specified by the owning component.

## Event idempotency keys (MUST)
Events MUST be idempotent across retries.

- **Event IDs:** every event MUST include a unique `event_id`.
- **Deterministic IDs:** producers SHOULD use deterministic IDs for retry safety (hash of stable fields such as `event`, `object_id`, `action_id`, `trace_id`).
- **Consumer dedup:** consumers MUST deduplicate by `event_id` and treat duplicates as no-ops.

## Race scenarios (required behaviors)
- **Concurrent watcher runs:** MUST not emit duplicate intents or events; DedupTaskQueue + `event_id` dedup are required.
- **Concurrent note edits:** MUST fail safe on version mismatch and avoid corrupting vault files.
- **Retry storms:** MUST be absorbed by deterministic IDs and consumer dedup; retries should not produce new side effects.

## Validation and tests
Current validation coverage includes tests for:

- **Watcher dedup:** concurrent watcher runs do not emit duplicate `watcher.run` or panel intents.
- **Optimistic locking:** concurrent writes fail safe with a version mismatch and no corruption.
- **Idempotency:** action replays (same `event_id`) do not re-apply side effects.

Representative test files:
- `tests/concurrency/test_dedup_task_queue.py`
- `tests/concurrency/test_event_dedup_store.py`
- `tests/concurrency/test_panel_action_idempotency.py`
- `tests/promotion/test_consumer_idempotency.py`
- `tests/architecture/test_events_outbox_contracts.py`

Useful commands:
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/concurrency tests/promotion/test_consumer_idempotency.py -m "not pg"`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_events_outbox_contracts.py -m "not pg"`
