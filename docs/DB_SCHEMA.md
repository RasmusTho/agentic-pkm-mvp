State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Human-readable snapshot of the current database schema and DB outbox bootstrap; migrations and bootstrap code remain the executable source of truth.
Temporal class: operational
Source of truth: code
Last verified against: app/stores/pg.py (2026-06-15)

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# DB Schema (Current Reality)

## Source Of Truth
- Runtime DDL in `app/stores/pg.py` (`_ensure_tables()`) defines the **active store** tables
  (`store_objects`, `store_vector_index`, `store_relations`, `store_relation_memberships`,
  `vector_index_meta`). These are created at runtime, **not** by Alembic.
- `app/services/outbox.py` (`bootstrap()`) defines the **DB outbox** table (canonical queue) at runtime.
- Alembic migrations under `app/alembic/versions/` define the legacy AMG-core
  (`objects`/`chunks`/`embeddings`/...) lineage only; see "Historical migration lineage" below. The
  active runtime does not depend on these tables.

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

The active store tables are created by runtime DDL in `app/stores/pg.py` (`_ensure_tables()`), not by
Alembic. The shapes below mirror that code (verified per the `Last verified against` frontmatter).
They remain mirror/projection surfaces and do not hold semantic authority over the note contract.

### `store_objects`
- `object_id` (`uuid`, PK)
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `created_at` / `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Notes:
  - `kind="note"` is a runtime/storage label and may represent a projection of a vault note rather
    than the full semantic class of the human artifact.

### `store_vector_index`
- `object_id` (`uuid`, PK)
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `embedding` (`double precision[]`, `NOT NULL`)
- `dim` (`integer`, `NOT NULL`) — the configured embedding guardrail dimension (`EMBED_DIM`, default `1536` from `DEFAULT_EMBED_DIM`); this is the requested/configured dimension, distinct from `nomic-embed-text`'s native `768`. See `docs/EMBEDDINGS.md`.
- `model` (`text`, `NOT NULL`)
- `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Interpretation:
  - the vector index is a derived runtime artifact, rebuildable from `store_objects` payloads
  - embeddings are stored as a `double precision[]` array; there is no `vector`-extension column and
    no separate `chunk_id` in the active store — similarity is computed in application code
  - every row carries its generating `model` and `dim`
  - embeddings do not participate in the identity-history/SCD pattern

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
`app/alembic/versions/`. They are retained as historical lineage only; the active runtime store is the
`store_*` set above and does not depend on these tables. Do not read these shapes as the current
contract. Note there is no `search_vector` column anywhere in the schema (active or legacy).

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

### `embeddings` (legacy)
- `id` (`uuid`, PK; default varies by migration)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `chunk_id` (`uuid`, nullable FK → `chunks.id`, `ON DELETE CASCADE`)
- `provider` (`text`, default `mock`)
- `dim` (`int`, default `1536`)
- `embedding` (either `double precision[]` with a cardinality check, or `vector` when vector extension is enabled in older branches)
- `created_at` (`timestamptz`, default `now()`)

### `decisions` (legacy)
- `id` (`uuid`, PK; default varies by migration)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
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
Created/ensured by `app/services/outbox.py:bootstrap()`:
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

## Explicit Deltas / Known Gaps
- The active runtime store is the `store_*` set defined by runtime DDL in `app/stores/pg.py`
  (`_ensure_tables()`). The AMG-core `objects`/`chunks`/`embeddings`/... tables under
  `app/alembic/versions/` are legacy lineage and are not on the active runtime path; an earlier
  revision of this doc mis-attributed the store tables to Alembic and listed a fabricated
  `search_vector` column, both corrected here.
- This repo still contains historical migration lineage and merge history under `app/alembic/versions/`. If you hit unexpected columns or migration conflicts, inspect the migration set and record the intended baseline delta in the same change.
- Companion-note and identity-history tables described in forward-line docs may not yet exist in
  the current physical schema; where absent, read them as forward-line schema direction rather than
  as already-shipped baseline tables.
