State: SoT v4.10 Reality-MVP (current).
# Data Model (Stores)

Reality-MVP uses the Store abstraction (memory/pg) backed by three active tables. Legacy SetDB/AMG concepts (sets, membership, audit) are not present in the current runtime.

## store_objects
- `object_id` UUID PK
- `kind` TEXT
- `source_ref` TEXT
- `payload` JSONB (holds Core-6 projection: `{id/uuid, title, origin, review_state, trust?, text/raw_text, ingest_fingerprint, source}` etc.)
- `created_at` TIMESTAMPTZ DEFAULT now()
- `updated_at` TIMESTAMPTZ DEFAULT now()

## store_vector_index
- `object_id` UUID PK (matches store_objects.object_id)
- `kind` TEXT
- `source_ref` TEXT
- `payload` JSONB (mirrors object metadata; may include title/origin/zone/trust for retrieval)
- `embedding` DOUBLE PRECISION[] (pgvector alternative when available)
- `model` TEXT
- `updated_at` TIMESTAMPTZ DEFAULT now()

## store_relations
- `src_id` UUID
- `dst_id` UUID
- `rel` TEXT (`supports|extends|contradicts|derived_from`; see RelationIndex)
- `payload` JSONB (evidence/source)
- `created_at` TIMESTAMPTZ DEFAULT now()

### Decisions (classifier / review hints)
- Memory and pg backends expose a lightweight `decisions` store (id, object_id, agent, kind, key, value, created_at) used by classifiers/reviewers. In pg this lives alongside the legacy `objects` table; in memory it is an in-process list.

### Legacy (not active in Reality-MVP)
- Historical tables such as `chunks`, `sets`, `membership`, and `audit` describe past designs and are not created/used by the current Store abstraction. Keep references for context only; they do not run in v4.10.
