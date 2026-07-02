---
name: Transform Provenance Stamp
description: Every store_vector_index upsert carries {source_ref, content_hash, chunk_policy_version, pipeline_version, embedding_identity} in the same upsert; index doctor gains a staleness check; reconcile re-embeds only stale rows
task_id: KERNEL-06
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-D1, CW-6"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-04]
depends_on: [STORE_SCHEMA_IN_MIGRATIONS.md]
can_parallelize_with: [RETRIEVAL_READS_DURABLE_INDEX]
---

# Transform Provenance Stamp

## Purpose

Vectors carry embedding identity (provider/model/dim/normalize — recorded per-row in
`store_vector_index` and `vector_index_meta`) but **not** the `content_hash` of the embedded text,
**not** `chunk_policy_version`, **not** a pipeline version. Chunk metadata v1
(`app/ingest/chunk_policy.py :: CHUNK_METADATA_FIELDS_V1`) is computed on demand and never persisted.
So "was this vector produced from this text" and incremental re-embedding are unanswerable, and
reconcile (#2752) works only for identity drift, not content/transform drift. Audit invariant
**I-D1** (derivation provenance), CW-6.

## What This Task Does

- Extend the `store_vector_index` upsert payload so every write carries
  `provenance = {source_ref, content_hash, chunk_policy_version, pipeline_version, embedding_identity}`.
  `content_hash` is a stable hash (e.g. `hashlib.sha256`) of the exact embedded text;
  `chunk_policy_version` is a new constant in `app/ingest/chunk_policy.py` (e.g. `CHUNK_POLICY_VERSION = "v1"`);
  `pipeline_version` is a single module-level embed-pipeline constant.
- The stamp rides the **same upsert statement** as the vector: `PgVectorIndex.upsert()`
  (`app/stores/pg.py`, approx. lines 361–435 at audit time) writes provenance inside the existing
  `payload` JSONB in the one `INSERT ... ON CONFLICT` — cross-task invariant #4 forbids a separate
  "stamp later" write.
- Index doctor gains a **read-only** staleness check: `app/index/doctor.py` compares stored
  `content_hash` against the current source hash and lists rows where they differ as re-embed
  candidates; surfaced via `app/cli/index_doctor.py` (the existing `--json`/`--coverage` command).
- `index reconcile` (`app/cli/index_rebuild.py`, the `reconcile` command approx. line 425 at audit
  time) re-embeds **only** stale rows (content_hash mismatch), proven incremental on a fixture vault
  — matching cross-task invariant #5 (doctor detects, reconcile repairs, nothing auto-mutates).

## Concretely

```bash
pytest -q tests/index/test_provenance_stamp.py
pytest -q -m pg tests/indexer/test_provenance_stamp_pg.py   # stamp rides the upsert
```

## Why This Matters

Deterministic replay/backfill and "re-embed only what changed" require provenance that does not
exist today. Persisting `content_hash` per vector makes incremental re-embedding cheap and
auditable, and lets the doctor distinguish stale-content from missing-content.

## Acceptance Criteria

- [ ] Every `PgVectorIndex.upsert()` write persists
      `provenance ⊇ {source_ref, content_hash, chunk_policy_version, pipeline_version, embedding_identity}`.
      Verify: `tests/index/test_provenance_stamp.py::test_upsert_writes_provenance`
- [ ] Enforcement AC: the stamp is written in the same statement as the vector — the test drives the
      real `PgVectorIndex.upsert()` production entrypoint and asserts a single upsert round-trip
      yields both embedding and provenance (no second write).
      Verify: `tests/indexer/test_provenance_stamp_pg.py::test_stamp_rides_the_upsert`
- [ ] Index doctor reports content-hash staleness as a read-only re-embed candidate listing (no
      mutation).
      Verify: `tests/index/test_provenance_stamp.py::test_doctor_lists_stale_candidates`
- [ ] `index reconcile` re-embeds only stale rows: unchanged rows are untouched on a fixture vault.
      Verify: `tests/index/test_provenance_stamp.py::test_reconcile_incremental_on_stale_only`

## How to Verify (Pre-Merge)

1. `pytest -q tests/index/test_provenance_stamp.py`
2. `pytest -q -m pg tests/indexer/test_provenance_stamp_pg.py` against local Postgres (`make db-up`).
3. Full `pytest -q -m "not pg"` (touches the embed/index path); `ruff check app tests`.

## Out of Scope

- Retrieval read-path rewiring (KERNEL-05).
- Event-topic payload schemas (KERNEL-08).
- Any change to embedding identity resolution or the reconcile identity-drift path (#2752 owns that).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-D1, CW-6`
- `docs/EMBEDDINGS.md`, `docs/DATA_MODEL.md :: store_vector_index` (writeback at promotion)
- `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md`

## Related GitHub Issues

Extends the closed **#2324** metadata/provenance completeness work (which observed missing
W3-SPINE-01 fields; this task *persists* the transform provenance so staleness is detectable). One
bounded issue. TCD hint: Sonnet / high effort (persistence + doctor + reconcile touch the index path;
verification is mechanical once the payload shape is set).
