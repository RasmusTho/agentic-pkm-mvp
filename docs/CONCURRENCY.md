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
  Vault text producers that pass a content hash as `expected_version` MUST bind the decoded UTF-8
  text and SHA-256 to the same exact raw filesystem read. Direct read/transform/write producers use
  `read_note_text_with_version`; aggregate scanners may carry an equivalent hash from the raw bytes
  they decoded. Re-encoding `Path.read_text()` is not equivalent because universal newline handling
  can turn CRLF into LF and falsely classify an unchanged note as stale.
- **Class boundary:** an `expected_version` request is valid only for a `REWRITTEN` note. The
  filesystem adapter classifies the canonical target relative to the canonical vault root and
  rejects an expected-version request for `CREATE_ONCE` or `APPEND_ONLY` before mutation instead
  of classifying a lexical alias or silently ignoring the token. The absolute helper preserves the
  caller-authorized lexical vault-relative locator for expected-version writes, and the adapter
  rejects any locator that already resolves through an alias. Its CAS opens the parent by walking
  every locator component from an anchored canonical vault-root descriptor with
  `O_DIRECTORY|O_NOFOLLOW`; re-walking that chain before linearization and receipt detects leaf or
  ancestor redirects after the alias check. Watcher admission resolves the vault-relative path
  against the canonical vault root and rejects symlinked or escaping aliases; both watcher paths
  recheck that policy before writeback.
- **Mismatch behavior:** when the first filesystem-seam comparison finds an already-stale rewritten note, the canonical note is left unchanged and the caller's proposed bytes are durably staged beside it with the shared `(... conflicted copy ...)` grammar. The low-level adapter's returned `WriteReceipt` reports `outcome="conflict_staged"`, the vault-relative artifact path, writer identity, and UTC write time. The shared production helpers preserve failure semantics for existing callers: `write_note_from_absolute` and `write_note_relative` raise `KnowledgeWriteConflict` carrying that receipt unless a conflict-aware caller explicitly opts into receiving the staged outcome. Normal return from those helpers therefore still means the canonical write landed; downstream success acknowledgements must not run for a staged sibling. The artifact is a Markdown sibling so the shared conflict classifier can quarantine it before watcher work. Initial-stale publication keeps a trusted hidden hard link to the exact proposal through final public-artifact verification; only then may identity-guarded cleanup remove it. Every exclusive staging open captures the controlled inode identity before write, flush, or `fsync`, so a pre-publication I/O failure identity-cleans its partial hidden entry. During initial-stale candidate publication, the complete proposal remains on its prior trusted rewrite-staging path. If another directory writer replaces the public name before that receipt fence, the operation fails without a receipt and retains the trusted proposal link for recovery. Missing targets and races after that first comparison still fail safe with `KnowledgeWriteConflict` (no overwrite or stale resurrection); those failures retain recoverable bytes without reporting a successful staged outcome. Filesystem content hashes are hashes of raw on-disk bytes, not newline-normalized text. Rewritten-note compare-and-swap anchors the canonical vault root, walks every parent component without following symlinks, and opens the target parent plus its `_conflicts` child as non-symlink directory descriptors. It then performs staging, validation, atomic same-filesystem exchange, artifact movement, rollback, and cleanup relative to those held descriptors. It re-walks the root-to-parent chain and verifies root, parent, and conflict identities immediately before linearization and again before returning a receipt. Immediately after exchange it verifies that the displaced entry is the exact inode opened before the final version check; a leaf replacement in the last check/exchange gap triggers an atomic compensating exchange before any artifact move or read, restoring the replacement and retaining the proposal. Renaming, replacing, or aliasing any authorized path component therefore produces `KnowledgeWriteConflict`, never a false successful receipt for a non-canonical write; displaced content remains retained through the held descriptors. The displaced original is verified after the exchange and atomically restored if its bytes or permission mode changed at the linearization point. Because an external process may still hold and later save through the displaced inode, every successful optimistic exchange retains that inode beside the actual target as `_conflicts/... (conflicted copy ...).md.conflict`; it is never unlinked automatically. The non-Markdown extension keeps safety bytes out of normal search/index/projection readers. File data and every directory mutation are `fsync`ed before success is reported. Any additional content displaced by a rollback race—or retained when rollback itself fails—uses the same durable location. Cleanup failures are diagnostic-only and cannot mask the committed write or primary conflict. Platforms without descriptor-relative no-follow access or an atomic exchange primitive fail closed.
- **No silent merges:** automatic merges are not allowed unless explicitly specified by the owning component.
- **Acknowledgement fence:** panel note updates prepare their Markdown/events without persisting
  executed IDs or dispatching plans, land the canonical version-checked write, and only then persist
  non-empty executed IDs and dispatch/emit eligible events. This applies to the note-update service
  and both direct watcher paths. Mutation-capable watcher policy first uses the authoritative
  note-class classifier over a canonical non-symlink path and admits only `REWRITTEN` paths;
  `CREATE_ONCE` sources, symlink aliases, and append-only
  paths do not enter UUID healing, panel preparation, writeback, or acknowledgement even when they
  contain an AI fence. A stale or staged-conflict result performs none of those
  acknowledgement effects, leaves the prior snapshot unchanged where one exists, and is counted by
  the note watcher as skipped/deferred rather than processed. Only an attached
  `conflict_staged` receipt is a known stale/deferred outcome; a receiptless or other
  `KnowledgeWriteConflict` is indeterminate and propagates as an error because the canonical write
  may already have linearized. Direct watcher writeback uses the same hardened knowledge-write
  helper as service flows; the check-then-`write_bytes` `OptimisticWriteGuard.write_if_unchanged`
  primitive is not an atomic CAS and MUST NOT authorize rewritten vault notes.

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
