---
name: Commit Entity-Review Operation and Outbox Visibility
description: Add the narrow durable merge-operation journal and require fresh committed operation/event visibility before an entity-review queue entry can be cleared.
task_id: EROJ-01
source_anchor: "docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Cross-task partial-failure matrix"
parent_capability: Entity-Review Operation Journal
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Commit Entity-Review Operation and Outbox Visibility

## Purpose

Make the existing human-confirmed entity-review merge restart-safe at the transaction boundary. A
merge receives one durable operation identity before its first register effect. After the register
effect is proven, the operation's event evidence is committed atomically in Postgres. The pending
queue entry is removed only after a fresh transaction can observe that commit.

## What This Task Does

- Add one migration-owned `entity_review_operations` table and a narrow
  `app/heimdal/entity_review_operation_journal.py` store. The row binds:
  active vault identity; deterministic `operation_id`; `queue_entry_id`; decision-list position;
  SHA-256 digest of the exact human-authored decision mapping; original `from_id` and `into_id`;
  monotonic operation state; deterministic outbox event id/idempotency key; and timestamps.
- Derive `operation_id` from the immutable tuple in INV-EROJ-2. An identical retry selects the same
  row; a changed decision digest for the same queue entry fails closed.
- Commit the initial operation row before the first entity-register note write. Record only
  monotonic states; never infer completion from the absence of `pending`.
- After source and target note effects are validated, atomically commit the operation's
  event-committed state and one `heimdal.register.entity.merged` outbox row in a journal-owned
  transaction. The event retains original `from_id`, original `into_id`, and `operation_id`.
- Use a separate/fresh connection or transaction to verify the committed operation and matching
  outbox row before `apply_human_review_decisions` may remove that queue entry.
- Refuse caller-supplied transaction visibility as terminal proof. Existing call sites may pass a
  connection for other work, but a row visible only to that transaction cannot authorize queue clear.
- Make the schema assert-only outside tests, add the Alembic producer, update create-on-demand test
  producers/fixtures, and fail loud with migration guidance when the schema is missing.
- Update the current owner contracts touched by this behavior in the implementation PR:
  `docs/DB_SCHEMA.md`, `docs/EVENTS.md`, and the entity-review human-flow contract. Do not update
  `docs/STATUS.md` to claim full capability acceptance yet.

## Concretely

For decision list item `i` on queue entry `q`, the applicator commits operation `op` before invoking
the existing register merge. If it stops after either note write, retry loads `op` and validates the
exact effect. Once both effects exist, one Postgres transaction advances `op` and inserts its
deterministically keyed outbox row. Only a second transaction's read can authorize the governed
`entities/review.md` write that removes `q`.

Task 1 deliberately refuses recovery if the current target has evolved after the original note
effect. EROJ-02 supplies that proof. This preserves a safe, serial stopping point.

## Why This Matters

Postgres lets a transaction read its own uncommitted insert. Treating that read as durability can
clear the only retry anchor from `pending`, after which rollback removes the outbox event. A
fresh-transaction visibility fence turns “the writer saw it” into “the system committed it” without
moving entity authority into the database.

## Acceptance Criteria

- [ ] The operation identity is deterministic across retries and binds the active vault, queue entry,
      decision position and digest, and original entity pair; a changed digest fails closed.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_operation_identity_binds_exact_human_decision`
- [ ] The initial journal row commits before the first register note effect.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_operation_claim_commits_before_first_register_effect`
- [ ] The event-committed journal state and exactly one matching outbox event commit atomically, with
      original `from_id`, original `into_id`, and `operation_id`.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_merge_event_commit_is_visible_on_fresh_connection_before_pending_clear`
- [ ] A caller-owned transaction that sees its own outbox insert cannot clear `pending`; after
      rollback, retry commits one event and clears only after fresh visibility.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_caller_transaction_rollback_cannot_clear_pending_or_hide_merge_event`
- [ ] A stop after both register effects but before event commit resumes the same operation, emits one
      event, and preserves the append-only decision mappings byte-for-byte.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_effect_before_event_commit_recovers_one_durable_event`
- [ ] `apply_human_review_decisions` can clear a merge entry only through the committed journal
      visibility fence; reject and pre-application undo retain their current semantics.
      Verify: `tests/heimdal/test_entity_confirm.py::test_apply_merge_uses_committed_journal_before_pending_clear`
- [ ] The journal table is Alembic-owned and assert-only outside tests, with every bootstrap/test
      producer updated and stale schema failing with `alembic upgrade head` guidance.
      Verify: `tests/migrations/test_entity_review_operation_journal_schema_parity.py::test_entity_review_operation_journal_schema_matches_head`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/heimdal/test_entity_review_operation_journal.py tests/heimdal/test_entity_confirm.py`
- `python3 -m pytest -q tests/migrations/test_entity_review_operation_journal_schema_parity.py`
- `python3 -m pytest -q -m "not pg" tests/heimdal tests/migrations`
- `ruff check app tests`
- `mypy app`
- Run the caller-transaction rollback test against Postgres, not a fake connection.
- Full Tier-3 independent review and current-SHA CI; post exact results and owner-doc writeback to the
  parent before EROJ-02 is made ready.

## Out of Scope

- Proving recovery after the original target later merges or splits (EROJ-02).
- Globally unique complement ids, legacy complement compatibility, or repeated split recovery
  (EROJ-03).
- A generic journal/saga API, worker, event bus, graph, second outbox, or UI.
- Changing the human decision vocabulary or making automatic identity decisions.

## Restart / Durability Posture

Every restart begins from the committed operation row plus canonical entity notes. An absent
operation means no effect may begin. A non-terminal row resumes the same operation. A terminal
event-commit row without queue clear is safe to finish after fresh visibility. Unknown states,
digest drift, or effect mismatch leave `pending` unchanged and fail loud.

## TCD Capability Guidance

Use Codex Sol / xhigh reasoning (or equivalent highest-ceiling capability). This slice combines an
Alembic migration, caller-vs-owned transaction semantics, a multi-store state machine, and a
protected data-loss failure previously missed after multiple repair rounds. First run the focused
real-Postgres rollback/visibility proof, then the affected suites, independent mechanism review, and
current-SHA CI. Do not fan out implementation.

## Related Docs

- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`
- `docs/RUNTIME_CORRECTNESS_KERNEL/TRANSACTIONAL_VAULT_SYNC.md`
- `docs/DB_SCHEMA.md`
- `docs/EVENTS.md`
- `docs/CONCURRENCY.md`
- `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md`

## Related GitHub Issues

Filed as [#4350](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4350), the first serial child of
parent validation hub [#4349](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4349). It is the
only initially `agent:ready` issue. #4253 is exhausted evidence only and must not be reopened.
