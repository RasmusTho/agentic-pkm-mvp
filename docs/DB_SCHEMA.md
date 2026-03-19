State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Human-readable snapshot of the current database schema and DB outbox bootstrap; migrations and bootstrap code remain the executable source of truth.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# DB Schema (Current Reality)

## Source Of Truth
- Alembic migrations under `app/alembic/versions/` define the **store** tables/views.
- `app/services/outbox.py` (`bootstrap()`) defines the **DB outbox** table (canonical queue) at runtime.

This document is a human-readable snapshot of what the code creates/uses in the v5.5 baseline. If you change the schema, update this doc in the same PR.

Related docs:
- `docs/DATA_MODEL.md` for semantic ownership and persistence-surface meaning
- `docs/EVENTS.md` for the canonical outbox envelope carried in `outbox.payload`
- `docs/OPERATIONS.md` for runtime health checks involving the DB outbox
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current normalization recommendation on
  artifact/projection boundaries and compressed state vocabulary

Interpretation rule:
- schema terms such as `objects`, `kind`, `payload`, and `outbox` describe the current physical
  representation layer.
- they must not be read as the canonical ontology of the domain.

## Core Tables (Store)

### `objects`
- `id` (`uuid`, PK)
- `kind` (`text`)
- `source_ref` (`text`, optional in some historical migrations)
- `payload` (`jsonb`, default `{}`)
- `created_at` / `updated_at` (`timestamptz`, default `now()`)
- Notes:
  - Some historical branches add an optional `uuid` column + index; do not rely on it unless your migration head includes it.
  - `kind="note"` is currently a runtime/storage label and may represent a projection of a vault
    note rather than the full semantic class of the human artifact.

### `chunks`
- `id` (`uuid`, PK)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `idx` (`int`)
- `offset_start` / `offset_end` (`int`)
- `text` (`text`)
- `created_at` (`timestamptz`, default `now()`)

### `embeddings`
- `id` (`uuid`, PK; default varies by migration)
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `chunk_id` (`uuid`, nullable FK → `chunks.id`, `ON DELETE CASCADE`)
- `provider` (`text`, default `mock`)
- `dim` (`int`, default `1536`)
- `embedding` (either `double precision[]` with a cardinality check, or `vector` when vector extension is enabled in older branches)
- `created_at` (`timestamptz`, default `now()`)

### `decisions`
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

### `membership`
The current baseline retains the **composite** key form:
- `object_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`)
- `set_id` (`uuid`, FK → `objects.id`, `ON DELETE CASCADE`) (sets are stored as objects in this baseline)
- `created_at` (`timestamptz`, default `now()`)
- `PRIMARY KEY (object_id, set_id)`

### Views / Helpers
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
- This repo still contains historical migration lineage and merge history under `app/alembic/versions/`. If you hit unexpected columns or migration conflicts, inspect the migration set and record the intended baseline delta in the same change.
