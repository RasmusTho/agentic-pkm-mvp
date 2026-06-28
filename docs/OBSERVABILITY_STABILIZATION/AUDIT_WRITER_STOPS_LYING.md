---
name: Audit Writer Stops Lying
description: >
  Align the audit INSERT to the table schema, supply the NOT-NULL id, and
  replace the bare except so failures log at ERROR instead of silently
  writing zero rows.
task_id: OBSSTAB-03
source_anchor: >
  app/services/audit.py :: audit_event ;
  app/alembic/versions/202510241200_sot41_amg_core.py :: audit table
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - READINESS_REFLECTS_DEPENDENCIES.md
  - RUNTIME_VERSION_MARKER.md
  - DEV_DB_SNAPSHOT_RESTORE.md
---

# Audit Writer Stops Lying

## Purpose

The audit INSERT uses columns (`trace_id, event, payload, created_at`) that do
not exist in the migration-defined schema; every pg-backed write raises and is
swallowed silently. This task aligns the writer to the schema, supplies the
required `id`, and replaces the bare except with an ERROR log so failures are
visible.

## What This Task Does

1. Fixes `app/services/audit.py:53-57`: replaces the INSERT
   `(trace_id, event, payload, created_at)` with the actual migration columns
   `(id, object_id, agent, action, ts, trace_id, details)`.  Supplies a
   generated UUID for `id` (the `audit` table at migration line 103 declares
   `id UUID PRIMARY KEY` with no default).  Maps `event -> action`,
   `payload -> details`, `created_at -> ts`.
2. Replaces `app/services/audit.py:65-67` (`except Exception: return`) with
   `except Exception: logger.error(...)` — the writer stays non-fatal but the
   failure is now visible.
3. Adds `tests/services/test_audit_writer.py` with three tests (see ACs).

## Concretely

Trigger a privileged action against a real pg backend:

```
SELECT count(*) FROM audit;
-- returns > 0 after the fix; returned 0 before
```

Force a column mismatch (e.g. point at a schema with a renamed column):

```
# app logs an ERROR line such as:
# ERROR app.services.audit - audit INSERT failed: column "event" does not exist
# the calling action still completes (non-fatal)
```

The call chain: `app/promotion/gates.py:50,81` → `audit_log` in
`app/agents/base/audit.py:66-74` → `audit_event` in `app/services/audit.py`.
`agents/base/audit.py:73-75` has its own bare swallow; that layer's swallow is
intentional (cache/file fallback already succeeded) and is out of scope here.

## Why This Matters

In prod (pg backend) every `audit_event` call raises `UndefinedColumn` and is
swallowed at `app/services/audit.py:65-67` — zero durable audit rows are ever
written. Promotion-gate overrides (`app/promotion/gates.py:50,81`) route
through this dead path believing they logged (risk R2 — a correctness lie, not
missing-data noise). The OWNER DECISION is to fix the silent failure only; the
DB audit table is not the durable system-of-record long-term (note-backed audit
is a Storage-lifecycle epic concern).

## Acceptance Criteria

- [ ] An end-to-end privileged action writes at least one audit row on a real pg.
  - Verify: `tests/services/test_audit_writer.py::test_audit_row_written_on_action`
- [ ] A forced INSERT failure logs at ERROR and does NOT abort the calling action.
  - Verify: `tests/services/test_audit_writer.py::test_audit_insert_failure_logs_error_non_fatal`
- [ ] The writer's column list matches the migration schema columns.
  - Verify: `tests/services/test_audit_writer.py::test_audit_columns_match_migration`

## How to Verify (Pre-Merge)

```bash
# All three tests (requires pg):
pytest tests/services/test_audit_writer.py -v

# Full not-pg suite must stay green:
pytest -m "not pg" --timeout 120
```

## Out of Scope

- Durable audit-of-record / note-backed audit (Storage-lifecycle epic).
- Routing all privileged writes (vault/settings/promotion) through audit.
- Retention or pruning of the audit table.
- The second bare swallow at `app/agents/base/audit.py:73-75` (that layer's
  cache/file fallback has already succeeded; swallowing the pg call is
  intentional at that layer).

## Related Docs

- `app/services/audit.py` — writer under repair (INSERT at lines 53-57, bare
  except at lines 65-67)
- `app/alembic/versions/202510241200_sot41_amg_core.py` — audit table DDL at
  lines 100-112 (`id UUID PRIMARY KEY`, `agent NOT NULL`, `action NOT NULL`,
  `details JSONB NOT NULL`)
- `app/agents/base/audit.py` — call chain entry point; calls `audit_event` at
  lines 66-74
- `app/promotion/gates.py` — promotion-gate callers at lines 50 and 81

## Related GitHub Issues

Child of the parent Observability Stabilization feature issue. Independent of
other OBSSTAB tasks — safe to deliver in parallel with OBSSTAB-01, OBSSTAB-05,
and OBSSTAB-07.
