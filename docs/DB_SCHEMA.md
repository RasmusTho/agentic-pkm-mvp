State: Partially outdated relative to SoT v4.10; reflects legacy tables and current store schema.
# DB schema (Reality-MVP vs legacy)

## Active tables (Store abstraction)
- `store_objects(object_id UUID PK, kind TEXT, source_ref TEXT, payload JSONB, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
- `store_vector_index(object_id UUID PK, kind TEXT, source_ref TEXT, payload JSONB, embedding DOUBLE PRECISION[], model TEXT, updated_at TIMESTAMPTZ)`
- `store_relations(src_id UUID, dst_id UUID, rel TEXT, payload JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ, PRIMARY KEY (src_id, dst_id, rel))`
- Optional `decisions(id UUID PK DEFAULT gen_random_uuid(), object_id UUID, agent TEXT, kind TEXT, key TEXT, value JSONB, created_at TIMESTAMPTZ)` used by classifiers/reviewers.

## Legacy tables (historical; not used in Reality-MVP)
- `objects`, `chunks`, `embeddings` (legacy ingestion/indexing pipeline)
- `sets`, `membership` (SetDB/AMG concepts)
- `audit` (historical audit log table)

## Indexes (when using pgvector)
- `store_vector_index.embedding` can use pgvector (ivfflat/hnsw) when available; the current pg schema stores embeddings as arrays for compatibility.
- Add btree indexes on `store_objects.kind` / `source_ref` as needed; defaults are minimal for local dev.
