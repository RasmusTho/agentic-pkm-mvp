---
name: Store Schema In Migrations
description: Move store_* and vector_index_meta DDL into Alembic; _ensure_tables becomes assert-only outside tests
task_id: KERNEL-04
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-S3"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: []
depends_on: []
can_parallelize_with: [TRANSACTIONAL_VAULT_SYNC, SINGLE_STORE_GENERATION]
---

# Store Schema In Migrations

## Purpose

The store tables (`store_objects`, `store_vector_index`, `store_relations`,
`store_relation_memberships`, `vector_index_meta`) are created imperatively by
`app/stores/pg.py :: _ensure_tables()` (approx. lines 37–110), outside Alembic. Meanwhile Alembic
owns a superseded `embeddings` table. Two schema authorities for one database means fresh
environments, prod, and CI can silently diverge (audit invariant **I-S3**).

## What This Task Does

- Add one forward-only Alembic migration creating the five store tables + indexes exactly as
  `_ensure_tables()` does today (including identity columns `dim/model/provider/normalize` and the
  `vector_index_meta` singleton shape). Use `IF NOT EXISTS` semantics so existing environments
  no-op.
- Convert `_ensure_tables()` (and `_backfill_identity_columns()` bootstrap behavior) to
  **assert-only** outside tests: if a table is missing in a Postgres-backed runtime, raise with a
  "run migrations" message instead of creating. Test environments may keep create-on-demand via an
  explicit flag the test fixtures set.
- Decide the legacy `embeddings` table's fate explicitly: mark deprecated in `docs/DB_SCHEMA.md`
  and drop it in this migration **only if** KERNEL-03's caller inventory confirms zero readers;
  otherwise record the follow-up in the issue.
- Update `docs/DB_SCHEMA.md` so the store tables are documented as migration-owned.

## Concretely

```bash
alembic upgrade head            # on a fresh DB
pytest -q -m pg tests/migrations/test_store_schema_parity.py
```

The parity test runs migrations on a scratch schema and compares the resulting DDL (via
information_schema / pg_dump normalization) with what `_ensure_tables()` would have produced —
asserting the two authorities are now one.

## Why This Matters

Migration-owned schema is the precondition for every later schema-carrying change (KERNEL-06
provenance columns, payload `schema_version`). Without it, "works on my machine" schema drift is
undetectable and promotion runbooks cannot reason about migration delta.

## Acceptance Criteria

- [ ] Fresh-DB `alembic upgrade head` produces all five store tables with indexes and identity
      columns; parity with the audited `_ensure_tables()` shape.
      Verify: `tests/migrations/test_store_schema_parity.py::test_fresh_db_parity`
- [ ] Existing environments no-op (idempotent migration; no data movement).
      Verify: `tests/migrations/test_store_schema_parity.py::test_upgrade_idempotent_on_existing`
- [ ] Postgres runtime with a missing store table fails loud with a migration hint (enforcement AC:
      asserted through `PgObjectStore`/`PgVectorIndex` construction, the production call sites).
      Verify: `tests/stores/test_ensure_tables_assert_only.py::test_missing_table_raises`
- [ ] `docs/DB_SCHEMA.md` documents store tables as migration-owned and states the `embeddings`
      table decision.
      Verify: doc writeback at `docs/DB_SCHEMA.md :: store tables`

## How to Verify (Pre-Merge)

1. Local Postgres: `make db-up`, `alembic upgrade head` on a fresh database, then
   `pytest -q -m pg tests/migrations/ tests/stores/`.
2. Full `pytest -q -m "not pg"` (memory backend unaffected).
3. `ruff check app tests`.

## Out of Scope

- Any data backfill (identity backfill already exists and stays).
- Downgrade paths (repo posture is forward-only).
- New columns (KERNEL-06 adds provenance fields in its own migration).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-S3`
- `docs/DB_SCHEMA.md`, `.codex/skills/prepare-promotion/SKILL.md` (migration-delta enumeration
  depends on migrations being the single authority)

## Related GitHub Issues

One bounded issue. TCD hint: Opus / high effort (migration surface — AGENTS.md routes
data/migration work to the strong-capability tier; the change is small but the defect blast radius
is prod schema). Cheapest acceptable: Sonnet / high **only** if the implementing agent limits
itself strictly to the parity-tested shape.
