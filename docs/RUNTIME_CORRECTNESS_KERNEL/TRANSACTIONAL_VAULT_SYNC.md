---
name: Transactional Vault Sync
description: Wrap the objects + file_state + outbox mutation in vault sync in one DB transaction so state and event commit atomically
task_id: KERNEL-01
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-3"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: []
depends_on: []
can_parallelize_with: [SINGLE_STORE_GENERATION, STORE_SCHEMA_IN_MIGRATIONS, STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN, DEAD_LETTER_HEALTH_SIGNAL]
---

# Transactional Vault Sync

## Purpose

The transactional-outbox pattern exists so that a state mutation and the event announcing it commit
atomically. Today `sync_markdown()` performs them as separate statements, so a crash mid-sequence
leaves the DB partially updated or emits no event for a committed mutation — the event log cannot be
trusted for replay (audit invariant **I-S2**).

## What This Task Does

- In `app/services/vault_sync.py :: sync_markdown()` (the region spanning the objects upsert,
  `file_state` update, and `insert_object_and_outbox()` call — approx. lines 334–512 at audit time),
  wrap all DB statements for one note in a single explicit transaction (`BEGIN`/`COMMIT` on the
  shared connection, or the psycopg transaction context).
- Same treatment for `handle_rename()` (approx. lines 515–546): `objects.path` and
  `file_state.path` update atomically.
- The vault write (uuid heal via `_write_note()`) stays **outside** the DB transaction (different
  substrate) and stays first; the DB transaction begins only after the note read is stable.
- No behavior change on the happy path; rollback on any statement failure leaves zero partial rows.

## Concretely

```bash
pytest -q tests/integration/test_vault_sync_atomicity.py   # new test, pg-marked
```

The test monkeypatches/fault-injects a failure between the objects upsert and the file_state update
(and separately between file_state and outbox insert) and asserts: no `objects` row without its
`file_state` row, no committed state mutation without its outbox row, and vice versa. A rerun after
the injected crash converges to the fully-synced state.

## Why This Matters

Without atomicity, replaying the outbox cannot reconstruct state (events may be missing for
committed mutations), and doctors comparing objects↔file_state↔outbox report divergence that no one
can classify as bug vs crash residue. Every downstream kernel task (idempotency, schema registry,
provenance) assumes this seam is sound.

## Acceptance Criteria

- [ ] `sync_markdown()` commits objects + file_state + outbox for one note in one DB transaction;
      fault injection between any two statements yields all-or-nothing.
      Verify: `tests/integration/test_vault_sync_atomicity.py::test_sync_markdown_all_or_nothing`
- [ ] `handle_rename()` updates `objects.path` and `file_state.path` atomically.
      Verify: `tests/integration/test_vault_sync_atomicity.py::test_rename_atomic`
- [ ] Happy-path behavior unchanged: existing vault-sync and worker-consumption tests stay green.
      Verify: `pytest -q tests/services/test_vault_sync*.py tests/workers/test_outbox_worker_consumes_ingest.py`
- [ ] Enforcement is at the production call site, not a helper in isolation: the atomicity test
      drives `sync_markdown()` itself (the real entrypoint), not an extracted function.
      Verify: `tests/integration/test_vault_sync_atomicity.py` imports and calls `app.services.vault_sync.sync_markdown`

## How to Verify (Pre-Merge)

1. `pytest -q -m pg tests/integration/test_vault_sync_atomicity.py` (new; requires local Postgres —
   `make db-up` per `docs/DEV_WORKFLOW.md`).
2. Full `pytest -q -m "not pg"` (hot-path change; per repo rule sub-agents on shared/hot-path run
   the full not-pg suite, plus `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m uat_integrated_runtime`
   because vault sync is on the vault hot path).
3. `ruff check app tests`.

## Out of Scope

- Changing outbox schema, topics, or idempotency semantics (KERNEL-02).
- Making the vault write and DB write jointly atomic (different substrates; the companion/vault
  seam is governed by the continuity-set posture, not a transaction).
- Any retrieval or embedding change.

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-3` (crash-window analysis)
- `docs/EVENTS.md` (outbox contract), `docs/DB_SCHEMA.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (DB is derived; this task makes the
  derivation trustworthy, it does not change authority)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / high effort (transaction boundaries + fault-injection tests;
hidden correctness risk). Escalate to Opus if the connection-ownership refactor turns out to span
more than `vault_sync.py`.
