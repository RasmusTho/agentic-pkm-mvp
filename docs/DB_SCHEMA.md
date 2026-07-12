State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Human-readable snapshot of the current database schema and DB outbox bootstrap; migrations and bootstrap code remain the executable source of truth.
Temporal class: operational
Source of truth: code
Last verified against: app/stores/pg.py + app/alembic/versions/c2766a04d001_kernel04_store_schema_in_migrations.py + app/services/outbox.py + app/alembic/versions/f3a1c9d2e4b7_kernel05_outbox_schema_in_migrations.py + app/heimdal/observation_log.py + app/heimdal/cursor_store.py + app/alembic/versions/8b21e6a1f0c4_heim_observation_log_and_cursor.py (2026-07-06)

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# DB Schema (Current Reality)

## Source Of Truth
- The **active store** tables (`store_objects`, `store_vector_index`, `store_relations`,
  `store_relation_memberships`, `vector_index_meta`) are **migration-owned** (KERNEL-04, #2766):
  Alembic revision `c2766a04d001` creates them, and `app/stores/pg.py::_ensure_tables()` is
  assert-only outside tests — a Postgres runtime with a missing store table raises with a
  "run migrations" hint instead of creating schema. Test fixtures opt in to create-on-demand via
  `STORE_SCHEMA_AUTOCREATE=1`. Schema parity between the migration and the audited
  `_ensure_tables()` shape is asserted by `tests/migrations/test_store_schema_parity.py`.
- The **DB outbox** table (canonical queue) is **migration-owned** (KERNEL-05, #2850, follow-up to
  KERNEL-04): Alembic revision `f3a1c9d2e4b7` creates it, and
  `app/services/outbox.py::bootstrap()` is assert-only outside tests — a Postgres runtime with a
  missing outbox table/column raises `OutboxSchemaMissingError` with a "run migrations" hint instead
  of creating schema (the prior silent `except Exception: pass` around `ensure_schema` is gone). Test
  fixtures opt in to create-on-demand via the same `STORE_SCHEMA_AUTOCREATE=1` flag KERNEL-04
  established. Schema parity between the migration and the audited `bootstrap()` shape is asserted by
  `tests/migrations/test_outbox_schema_parity.py`.
- Alembic migrations under `app/alembic/versions/` define the legacy AMG-core
  (`objects`/`chunks`/`embeddings`/...) lineage; see "Historical migration lineage" below. Most of
  these are historical-only, **but `objects` and `decisions` remain on the active runtime path**: vault
  ingest writes `objects` via `app/stores/postgres.py` (`PgObjects.upsert`, reached through
  `app/ingest/vault_root.py` → `get_stores()`), and `app/services/decisions.py` reads/writes
  `decisions`. `chunks`/`embeddings`/`membership` are touched by the backfill job
  (`app/jobs/backfill.py`) and `app/store/membership_store.py` rather than purely historical.

This document is a human-readable snapshot of what the code creates/uses in the v5.5 baseline. The
runtime store shape is mirrored from `app/stores/pg.py`; if you change the store schema there, update
this doc in the same PR.

Related docs:
- `docs/DATA_MODEL.md` for semantic ownership and persistence-surface meaning
- `docs/EVENTS.md` for the canonical outbox envelope carried in `outbox.payload`
- `docs/OPERATIONS.md` for runtime health checks involving the DB outbox
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` for the file-based continuity artifact related to
  note identity repair
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current normalization recommendation on
  artifact/projection boundaries and compressed state vocabulary

Interpretation rule:
- schema terms such as `objects`, `kind`, `payload`, and `outbox` describe the current physical
  representation layer.
- they must not be read as the canonical ontology of the domain.
- DB state is rebuildable from vault notes + companion notes; schema descriptions here must not be
  interpreted as making DB semantically primary.

## Identity-metadata history (forward-line direction)

Forward-line documentation now reserves SCD-style history for identity-metadata fields only.

Typical identity-metadata fields:
- `uuid`
- `source_ref`
- bounded title continuity metadata when needed for repair
- continuity-oriented ingest/healing state

Expected physical shape when implemented:
- identity tracking table with `valid_from` / `valid_to`
- one active row per identity-metadata dimension under current validity

Scope limit:
- this SCD-style posture applies only to identity-metadata history
- it does not apply to chunks, embeddings, or summaries

## Derived-layer invalidation rule

Chunks, embeddings, and similar derived runtime artifacts should not use SCD-style history as the
default continuity model.

Instead they are:
- invalidated when source content or model assumptions change,
- replaced/rebuilt,
- and interpreted as derivative runtime state rather than identity ledger rows.

## Core Tables (Store)

The active store tables are migration-owned: created by Alembic revision `c2766a04d001`
(KERNEL-04, #2766), with `app/stores/pg.py::_ensure_tables()` asserting their presence (and running
the idempotent identity **data** backfill) rather than creating schema outside tests. The shapes
below mirror the migration (verified per the `Last verified against` frontmatter). They remain
mirror/projection surfaces and do not hold semantic authority over the note contract.

### `store_objects`
- `object_id` (`uuid`, PK)
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `created_at` / `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Notes:
  - `kind="note"` is a runtime/storage label and may represent a projection of a vault note rather
    than the full semantic class of the human artifact.
  - The retrieved-unit payload contract requires `artifact_id` / `stable_id`, `path`, `source_ref`,
    `language`, `origin`, `source_role`, `trust`, and canonical `review_state`. These are persisted
    in `payload` because the active table has no separate columns for those semantic projection
    fields beyond `object_id`, `kind`, and `source_ref`.
  - A source note's frontmatter `uuid` is lineage metadata. It may seed continuity, but a missing
    source-note `uuid` must not prevent indexing; runtime identity can be derived and persisted as
    `object_id`.
  - StorePort classification: rebuildable. The current object-store path is resolved through
    `app.stores.resolve_object_store_port`, with recovery posture anchored in vault notes and
    companion-note identity continuity rather than in this table as semantic authority.

### `store_vector_index`
- `object_id` (`uuid`, PK)
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `embedding` (`double precision[]`, `NOT NULL`)
- `dim` (`integer`, `NOT NULL`) — the configured embedding guardrail dimension (`EMBED_DIM`, default `1536` from `DEFAULT_EMBED_DIM`); this is the requested/configured dimension, distinct from `nomic-embed-text`'s native `768`. See `docs/EMBEDDINGS.md`.
- `model` (`text`, `NOT NULL`)
- `provider` (`text`, nullable) — the embedding provider that generated this row's vector (e.g. `ollama`, `gemini`). Added in the EMBEDREL-06 Phase A migration; backfilled from `vector_index_meta` for pre-existing rows.
- `normalize` (`boolean`, nullable) — whether this row's vector was L2-normalized. Added with `provider` in the same migration and backfilled the same way.
- `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Interpretation:
  - the vector index is a derived runtime artifact, rebuildable from `store_objects` payloads
  - embeddings are stored as a `double precision[]` array; there is no `vector`-extension column, and
    the primary key is still `object_id` (one row per whole note) — similarity is computed in
    application code
  - every row carries its full generating embedding identity tuple `(provider, model, dim, normalize)`; the index-level primary identity lives in `vector_index_meta`
  - the row `payload` carries the same retrieved-unit metadata as `store_objects` plus
    `embedding_identity`, so retrieval/ContextPack consumers can inspect stable id, locator,
    language, provenance/source-role, trust/review posture, and embedding identity from the
    retrieved unit
  - **chunk metadata schema v1 (#2323):** `app/ingest/chunk_policy.py::build_chunks` produces
    per-chunk metadata (`chunk_id`, `source_id`, `heading_path`, `char_start`, `char_end`,
    `language`, `provenance`; see `docs/EMBEDDINGS.md :: Oversized input handling` and
    `docs/DATA_MODEL.md :: store_vector_index`) reusing this table — no new chunk store or
    `chunk_id`-keyed table. `chunk_id` is a plain string compatible with
    `IncludedItem.chunk_ids: list[str]`. This does not change the PK or the served unit: rows stay
    keyed by whole-note `object_id` until an explicit, documented chunk-level-serving switch lands
  - an ordinary upsert must match the primary identity; a reconcilable fallback write may record a divergent per-row `provider`/`model`/`normalize` (with the same `dim`), making fallback-written vectors visible and reconcilable (EMBEDREL-06 Phase A, `app/stores/pg.py::PgVectorIndex.upsert`)
  - the `dim` guard is unconditional — a dimension mismatch fails loud and writes no row
  - embeddings do not participate in the identity-history/SCD pattern
  - **transform provenance stamp (KERNEL-06, #2768):** `payload.provenance` carries `{source_ref,
    content_hash, chunk_policy_version, pipeline_version, embedding_identity}`, written in the same
    upsert statement as the vector (never a separate write). `content_hash` is a `sha256` of the
    exact embedded text; the index doctor's read-only staleness check compares it against the
    current `store_objects` text, and `index reconcile` re-embeds only the rows that drifted. A
    B-tree expression index on `payload->>'content_hash'` (migration `699c97b7c007`) backs that scan.

### `store_relations`
- `src_id` (`uuid`, `NOT NULL`)
- `dst_id` (`uuid`, `NOT NULL`)
- `rel` (`text`, `NOT NULL`)
- `payload` (`jsonb`, `NOT NULL`, default `{}`)
- `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
- `PRIMARY KEY (src_id, dst_id, rel)`

### `store_relation_memberships`
- `src_id` (`uuid`, `NOT NULL`)
- `rel` (`text`, `NOT NULL`)
- `value` (`text`, `NOT NULL`)
- `payload` (`jsonb`, `NOT NULL`, default `{}`)
- `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
- `PRIMARY KEY (src_id, rel, value)`

### `vector_index_meta`
- `id` (`integer`, PK, `CHECK (id = 1)` — single-row identity record)
- `identity_json` (`text`, `NOT NULL`) — serialized embedding identity (provider, model, dim, normalize)
- `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Interpretation:
  - pins the active embedding identity so the index can detect provider/model/dim drift and require a
    rebuild rather than silently mixing dimensions.

## Historical migration lineage (legacy AMG-core)

The tables below are the legacy AMG-core schema defined by Alembic migrations under
`app/alembic/versions/`. The primary runtime store is the `store_*` set above, but **`objects` and
`decisions` from this set are still on the active runtime path** (vault ingest upserts `objects` via
`app/stores/postgres.py`; `app/services/decisions.py` reads/writes `decisions`), and
`chunks`/`embeddings`/`membership` are exercised by the backfill job and `membership_store`. The
remaining shapes here are historical lineage. Do not read these shapes as the current contract. Note
there is no `search_vector` column anywhere in the schema (active or legacy).

### `objects` (legacy)
- `id` (`uuid`, PK)
- `kind` (`text`)
- `source_ref` (`text`, optional in some historical migrations)
- `payload` (`jsonb`, default `{}`)
- `created_at` / `updated_at` (`timestamptz`, default `now()`)

### `chunks` (legacy)
- `id` (`uuid`, PK)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `idx` (`int`)
- `offset_start` / `offset_end` (`int`)
- `text` (`text`)
- `created_at` (`timestamptz`, default `now()`)

### `embeddings` (legacy, **deprecated — kept, not dropped**)

KERNEL-03 (#2765) caller inventory: the only store-layer code path writing this table
(`app/store/vector_store.py`) had zero callers and was deleted; no writer of `embeddings` remains
anywhere in `app/` (guard:
`tests/architecture/test_single_store_writer.py::test_one_writer_per_table` asserts zero writers).

KERNEL-04 (#2766) decision: the table is **deprecated in this document and NOT dropped**; the
`c2766a04d001` migration intentionally does not touch it, because the zero-**readers**
precondition is not met — one read reference remains (`app/jobs/backfill.py` uses a
`NOT EXISTS (... FROM embeddings ...)` predicate when selecting objects to backfill, and
`view_chunks_missing_embeddings` reads it). The drop is a named follow-up recorded on issue
#2766: remove/replace the backfill read predicate and the view, then drop `embeddings` in its
own forward-only migration.

- `id` (`uuid`, PK; default varies by migration)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `chunk_id` (`uuid`, nullable FK → `chunks.id`, `ON DELETE CASCADE`)
- `provider` (`text`, default `mock`)
- `dim` (`int`, default `1536`)
- `embedding` (either `double precision[]` with a cardinality check, or `vector` when vector extension is enabled in older branches)
- `created_at` (`timestamptz`, default `now()`)

### `decisions` (legacy)
- `id` (`uuid`, PK; default varies by migration)
- `object_id` (`uuid`, nullable, FK → `objects.id`, `ON DELETE SET NULL` — realigned to the
  `audit.object_id` posture by `1a739d9494af_decisions_fk_set_null.py`, #2788; was
  `ON DELETE CASCADE` and `NOT NULL` before this migration, see D-5/D-7 in
  `docs/architecture/runtime-semantics.md :: Divergences`)
- `agent` (`text`, optional)
- `kind` (`text`, optional)
- `key` (`text`)
- `value` (`jsonb`)
- `created_at` (`timestamptz`, default `now()`)
- Typical indexes:
  - `decisions_object_id_idx`, `decisions_key_idx`
  - `(object_id, key, created_at desc)` for “latest decision” reads

Interpretation:
- rows in `decisions` are operational/system-side decision records.
- they are not automatically equivalent to human-approved commitments or receipts.
- like `audit`, decisions now **survive** object deletion (`object_id` goes `NULL` instead of the
  row being cascade-deleted), so judgment history is not silently lost if object cleanup (owner
  decision D-2 on #2778) ever lands.
- the writer (`app/services/decisions.py::insert_decision`/`latest_decision`) is fail-loud: a
  Postgres-configured-but-unreachable database raises instead of silently falling back to an
  in-process memory store; the memory path is reachable only via an explicit
  `STORE_BACKEND=memory` opt-in (mirrors the KERNEL-03 store-backend contract in
  `app/stores/provider.py::_resolved_backend`).

### `membership` (legacy)
The legacy baseline retains the **composite** key form:
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `set_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`) (sets are stored as objects in this baseline)
- `created_at` (`timestamptz`, default `now()`)
- `PRIMARY KEY (object_id, set_id)`

### Views / Helpers (legacy)
- `view_chunks_missing_embeddings`
- `view_objects_ready_for_projection`
- `latest_decision(object_id uuid, key text) -> jsonb`

## Canonical Queue (DB Outbox)
Migration-owned (KERNEL-05, #2850): Alembic revision `f3a1c9d2e4b7` creates the table exactly as the
audited `app/services/outbox.py::bootstrap()` produced it; `bootstrap()` is assert-only outside tests
(`STORE_SCHEMA_AUTOCREATE=1` opts test fixtures into create-on-demand):
- `outbox`
  - `id` (`uuid`, PK, default `gen_random_uuid()`)
  - `topic` (`text`)
  - `payload` (`jsonb`) (stores the serialized event envelope)
  - `created_at` (`timestamptz`, default `now()`)
  - `delivered_at` (`timestamptz`, nullable)
  - `attempts` (`int`, default `0`)
  - Indexes: `outbox_created_idx`, `outbox_delivered_idx`

Interpretation:
- the outbox is the canonical runtime queue,
- but the event payload is still an operational artifact layer rather than the whole domain model.

## Heimdal Observation Log (append-only, per-consumer cursor)

Migration-owned (#3039, Epic #3019 slice A2): Alembic revision `8b21e6a1f0c4` creates both tables;
`app/heimdal/observation_log.py`/`app/heimdal/cursor_store.py::_bootstrap_pg()` are assert-only
outside tests (`STORE_SCHEMA_AUTOCREATE=1` opts test fixtures into create-on-demand), mirroring the
KERNEL-04/KERNEL-05 precedent. See `docs/EVENTS.md :: Heimdal observation log` for the full contract.

- `heimdal_observation_log` — the canonical Heimdal <-> Mimer constituent seam; a separate table from
  `outbox`, never a `outbox` topic family.
  - `id` (`uuid`, PK) — the row id is the caller-derived idempotency key (same convention as
    `outbox.id`), not a random default.
  - `topic` (`text`, `NOT NULL`)
  - `payload` (`jsonb`, `NOT NULL`) — the reused outbox envelope (see `docs/EVENTS.md`)
  - `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
  - `sequence` (`bigserial`, `NOT NULL`) — monotone log position; the basis for cursor reads
  - Indexes: `heimdal_observation_log_seq_idx`, `heimdal_observation_log_topic_idx`
  - **No `delivered_at`/`attempts` columns** — unlike `outbox`, this is not a single-consumer work
    queue; every consumer reads the same rows independently via its own cursor.
  - **Append-only enforced by DB trigger** (`heimdal_observation_log_no_update`, HEIM-1): any
    UPDATE or DELETE against this table raises, independent of caller. The Python API also exposes
    no update/delete function.
- `heimdal_observation_cursor` — one row per consumer; consumers never share or affect each other's row.
  - `consumer_id` (`text`, PK)
  - `position` (`bigint`, `NOT NULL`, default `0`) — the next unread `sequence` for this consumer
  - `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)

Interpretation:
- the log is Heimdal's durable evidence stream; it is not authority over knowledge (HEIM-8),
- consumer projections built by replaying the log from a cursor are derived and rebuildable.

## Episode Resolution Engine tick-runtime state

Migration-owned (ERE-04, #3179): Alembic revision `a1b2c3d4e5f6` creates the table;
`app/episodes/engine_state.py` is assert-only (fail-loud `EngineStateSchemaMissingError` preflight
with a migration hint on every query; **no autocreate path at all** — unlike the Heimdal stores
there is no `STORE_SCHEMA_AUTOCREATE` opt-in here, test fixtures run the migration). See
`docs/EVENTS.md :: Secondary per-consumer cursor readers` for the consumer contract.

- `episode_engine_state` — generic key/value state for the segmentation tick
  (`app/episodes/segmenter.py::run_segmentation_tick`).
  - `key` (`text`, PK) — namespaced row families:
    - `cursor:vault.activity:<consumer_id>` — the engine's own durable read position over the
      `outbox` table's vault-activity topics (independent of `outbox.delivered_at`, which the
      worker dispatcher owns);
    - `open_segment:<scope>` — one scope's currently-open (not yet proposed) segment state;
    - `stream_watermark:<stream_id>` — max observed instant consumed per stream (observed-time
      quiescence frontier).
  - `value` (`jsonb`, `NOT NULL`)
  - `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)

Interpretation:
- pure rebuildable tick-runtime bookkeeping — never authoritative; Episode notes in the vault are
  the source of record (ADR-0051 OD-1/OD-2) and the `episodes` table is a rebuildable projection;
- recovery = reset this table's rows **together with** the `mimer.episode_resolution_engine` row in
  `heimdal_observation_cursor` (full both-stream replay is deterministic and emission-deduped); a
  single-stream reset is a skewed replay and is not a supported operator action (see the migration
  docstring).

## Explicit Deltas / Known Gaps
- The primary runtime store is the `store_*` set, migration-owned since Alembic revision
  `c2766a04d001` (KERNEL-04; `_ensure_tables()` is assert-only outside tests). The AMG-core tables
  under `app/alembic/versions/` are mostly legacy lineage,
  **except `objects` and `decisions`, which are still on the active runtime path** (vault ingest →
  `PgObjects.upsert` INSERTs into `objects`; `app/services/decisions.py` reads/writes `decisions`);
  `chunks`/`embeddings`/`membership` are touched by the backfill job and `membership_store`. An earlier
  revision of this doc mis-attributed the store tables to Alembic, listed a fabricated `search_vector`
  column, and over-broadly claimed none of the AMG-core tables were active — all corrected here.
- This repo still contains historical migration lineage and merge history under `app/alembic/versions/`. If you hit unexpected columns or migration conflicts, inspect the migration set and record the intended baseline delta in the same change.
- Companion-note and identity-history tables described in forward-line docs may not yet exist in
  the current physical schema; where absent, read them as forward-line schema direction rather than
  as already-shipped baseline tables.
