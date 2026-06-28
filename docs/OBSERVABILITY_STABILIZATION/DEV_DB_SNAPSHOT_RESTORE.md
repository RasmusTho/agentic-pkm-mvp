---
name: Dev DB Snapshot Restore
description: >
  Add make db-snapshot / db-restore for dev/test bug reproduction and an on-demand
  make db-dump-prod forensic snapshot — explicitly dev-ergonomics and forensics,
  not scheduled DR.
task_id: OBSSTAB-07
source_anchor: "Makefile :: db targets ; docs/OPERATIONS.md"
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - READINESS_REFLECTS_DEPENDENCIES.md
  - CONTAINER_HEALTH_SIGNALS.md
  - AUDIT_WRITER_STOPS_LYING.md
  - SCHEDULED_PROBE_AND_PUSH_ALERT.md
  - RUNTIME_VERSION_MARKER.md
  - FALSE_GREEN_REGISTER_AND_DOC_TRUTH.md
---

# Dev DB Snapshot Restore

## Purpose

Give dev/test a fast snapshot/restore cycle for bug reproduction, and an on-demand
forensic dump for prod incident investigation. This is explicitly dev-ergonomics and
forensics — not scheduled disaster recovery.

## What This Task Does

Adds three Makefile targets using `pg_dump` / `pg_restore`:

- `make db-snapshot` — dumps the dev/test DB to a timestamped file under a
  gitignored local dir (e.g. `.db-snapshots/`).
- `make db-restore` — restores from the most-recent (or named) snapshot.
- `make db-dump-prod` — writes a timestamped forensic dump from the prod DB on
  demand; no automated scheduling.

Documents the scope boundary in `docs/OPERATIONS.md`: this is NOT scheduled DR —
the vault is the durable system-of-record; the DB is disposable.

## Concretely

```bash
# snapshot the dev DB, mutate a row, then restore
make db-snapshot          # writes .db-snapshots/dev_20260628T120000.dump
psql $DATABASE_URL -c "UPDATE outbox SET topic='mutated' WHERE id=1"
make db-restore           # restores from latest .db-snapshots/dev_*.dump
psql $DATABASE_URL -c "SELECT topic FROM outbox WHERE id=1"
# → original value, not 'mutated'

# forensic prod dump (on demand, operator-initiated)
make db-dump-prod         # writes .db-snapshots/prod_20260628T120100.dump
```

Makefile variables to derive DSN: `DATABASE_URL` / `DB_DSN` via `app/db/dsn.py`
(`resolve_dsn()`). The snapshot dir is listed in `.gitignore`.

## Why This Matters

Bugfixing requires a reproducible snapshot — freeze a state, break it, restore,
retry. Without this, reproducing DB-state-dependent bugs requires manual SQL or
full reset. A forensic prod dump aids incident investigation without committing to
a scheduled DR system. Building scheduled DR instead would be effort against a
deliberately deprioritised risk and would still miss the most-interesting recent
outbox window. Risk ID: **OBSSTAB-07-R1** (dev cycle friction from un-reproducible
DB state).

## Acceptance Criteria

- [ ] `make db-snapshot` then `make db-restore` round-trips a known row in a dev DB.
  - Verify: `tests/ops/test_db_snapshot_restore.py::test_snapshot_restore_roundtrips_row`
- [ ] `make db-dump-prod` produces a timestamped dump file (smoke — does not
  require a live prod DB; mocks or a local stand-in are acceptable).
  - Verify: `tests/ops/test_db_snapshot_restore.py::test_db_dump_prod_writes_timestamped_file`
- [ ] `docs/OPERATIONS.md` includes a "DB snapshot/restore" section stating this is
  dev-ergonomics/forensic, not scheduled DR, and notes the vault is the durable SoR.
  - Verify: doc writeback at `docs/OPERATIONS.md :: DB snapshot/restore`

## How to Verify (Pre-Merge)

```bash
# Run the two new tests
PYTHONPATH=. pytest tests/ops/test_db_snapshot_restore.py -v

# Confirm the doc section exists
grep -n "DB snapshot/restore\|not scheduled DR" docs/OPERATIONS.md
```

## Out of Scope

- Scheduled/automated DR backups or cloud/off-host backup strategies.
- Using these dumps as a prod DR restore path.
- Storage-lifecycle retention/purge for old dump files (separate epic).
- Changing the channel isolation model or Makefile project scoping beyond
  adding the three new targets.

## Related Docs

- `Makefile` — channel compose vars (`COMPOSE_DEV`, `COMPOSE_TEST`, `COMPOSE_PROD`)
  and `DATABASE_URL` / `TEST_DATABASE_URL` wiring.
- `docs/OPERATIONS.md` — runtime operations reference; the new section goes here.
- `app/db/dsn.py` — `resolve_dsn()` is the canonical DSN resolver; use it in the
  target scripts to avoid hardcoding connection strings.

## Related GitHub Issues

Child of the parent Observability Stabilization feature issue. Fully independent
of all sibling tasks and may be delivered in any order or in parallel.
