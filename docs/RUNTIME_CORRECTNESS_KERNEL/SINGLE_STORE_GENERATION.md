---
name: Single Store Generation
description: Remove the legacy app/store/* writers and silent memory fallback; one writer per table, fail-loud backend resolution
task_id: KERNEL-03
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-1, I-S1, I-S4"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: []
depends_on: []
can_parallelize_with: [TRANSACTIONAL_VAULT_SYNC, STORE_SCHEMA_IN_MIGRATIONS]
---

# Single Store Generation

## Purpose

Two store generations coexist: the protocol-based `app/stores/*` (canonical) and the legacy
`app/store/object_store.py` / `app/store/vector_store.py` wrappers. The legacy `ObjectStore` falls
back to an in-process dict **silently on error** (approx. lines 72–75), so a prod process can run
"healthy" on volatile state. Audit invariants **I-S1** (single writer per table) and **I-S4** (no
silent fallback).

## What This Task Does

- Inventory every caller of `app/store/object_store.py` and `app/store/vector_store.py`; migrate
  each to the matching `app/stores/provider.py` accessor (`get_object_store()`,
  `get_vector_index()`).
- Delete the legacy modules (or reduce them to thin deprecation shims that raise, if a same-PR
  delete is too wide — then the follow-up delete is named in the issue).
- In `app/stores/provider.py :: _resolved_backend()` (line 22 at audit time): memory backend requires explicit
  `STORE_BACKEND=memory`; when Postgres is configured (`DATABASE_URL`/`DB_DSN` set) and
  unreachable, resolution **raises** instead of falling back. Test isolation keeps working via the
  existing autouse `force_memory_store_for_non_pg` fixture (which sets the explicit override).
- The legacy `embeddings` table's write path (if any caller remains) routes to `store_vector_index`;
  table removal itself belongs to KERNEL-04.

## Concretely

```bash
pytest -q tests/architecture/test_single_store_writer.py
STORE_BACKEND= DATABASE_URL=postgres://nowhere/x python -c "from app.stores.provider import get_object_store; get_object_store()"  # must raise, not fall back
```

## Why This Matters

A silent memory fallback converts every infrastructure failure into invisible data loss. Two write
generations mean "which table is true" has no stable answer — this is the enabling condition for the
retrieval-truth split that KERNEL-05 removes.

## Acceptance Criteria

- [ ] No production code imports `app/store/object_store.py` or `app/store/vector_store.py`.
      Verify: `tests/architecture/test_single_store_writer.py::test_no_legacy_store_imports`
- [ ] One writer per durable table: an architecture test enumerates modules issuing INSERT/UPDATE
      per store table and asserts the allowlist (stores protocols only).
      Verify: `tests/architecture/test_single_store_writer.py::test_one_writer_per_table`
- [ ] Postgres-configured-but-unreachable is fatal at first store access (enforcement AC — asserted
      through `get_object_store()`/`get_vector_index()`, the production call sites).
      Verify: `tests/stores/test_provider_fail_loud.py::test_unreachable_pg_raises`
- [ ] Memory backend only via explicit `STORE_BACKEND=memory`; existing non-pg suite stays green
      through the autouse fixture.
      Verify: `pytest -q -m "not pg"` green + `tests/stores/test_provider_fail_loud.py::test_memory_requires_explicit_opt_in`

## How to Verify (Pre-Merge)

1. `pytest -q tests/architecture/test_single_store_writer.py tests/stores/test_provider_fail_loud.py`
2. Full `pytest -q -m "not pg"`; `pytest -q -m pg tests/stores/` against local Postgres.
3. `ruff check app tests`.

## Out of Scope

- Moving DDL into Alembic (KERNEL-04).
- Retrieval-path rewiring (KERNEL-05).
- Any change to store protocol signatures.

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-1`
- `docs/DB_SCHEMA.md`, `docs/COMPONENTS.md` (update the store-layer description in the same PR)

## Related GitHub Issues

One bounded issue (a follow-up delete issue is acceptable if shims are kept one release). TCD hint:
Sonnet / high effort (multi-file caller migration; blast radius is the whole persistence layer, but
verification is mechanical).
