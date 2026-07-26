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
- **Mismatch behavior:** when the first filesystem-seam comparison finds an already-stale rewritten note, the canonical note is left unchanged and the caller's proposed bytes are durably staged beside it with the shared `(... conflicted copy ...)` grammar. The returned `WriteReceipt` reports `outcome="conflict_staged"`, the vault-relative artifact path, writer identity, and UTC write time. The artifact is a Markdown sibling so the shared conflict classifier can quarantine it before watcher work. Missing targets and races after that first comparison still fail safe with `KnowledgeWriteConflict` (no overwrite or stale resurrection); those failures retain recoverable bytes without reporting a successful staged outcome. Filesystem content hashes are hashes of raw on-disk bytes, not newline-normalized text. Rewritten-note compare-and-swap opens the target parent and its `_conflicts` child as non-symlink directory descriptors, then performs staging, validation, atomic same-filesystem exchange, artifact movement, rollback, and cleanup relative to those held descriptors. It verifies both descriptor identities against their canonical path entries immediately before linearization and again before returning a receipt. Renaming or replacing either directory therefore produces `KnowledgeWriteConflict`, never a false successful receipt for a non-canonical write; displaced content remains retained through the held descriptors. The displaced original is verified after the exchange and atomically restored if its bytes or permission mode changed at the linearization point. Because an external process may still hold and later save through the displaced inode, every successful optimistic exchange retains that inode beside the actual target as `_conflicts/... (conflicted copy ...).md.conflict`; it is never unlinked automatically. The non-Markdown extension keeps safety bytes out of normal search/index/projection readers. File data and every directory mutation are `fsync`ed before success is reported. Any additional content displaced by a rollback race—or retained when rollback itself fails—uses the same durable location. Cleanup failures are diagnostic-only and cannot mask the committed write or primary conflict. Platforms without descriptor-relative no-follow access or an atomic exchange primitive fail closed.
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
