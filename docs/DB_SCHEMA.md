# DB SCHEMA

## objects
- id uuid pk
- kind text
- source_ref text
- ts timestamptz default now()
- payload jsonb
- search_vector tsvector (generated from payload fields)

## chunks
- id uuid pk
- object_id uuid fk→objects(id) on delete cascade
- idx int
- offset_start int
- offset_end int
- text text

## embeddings
- id uuid pk (equals object_id for object-level, or chunk uuid if per-chunk)
- object_id uuid fk→objects(id)
- model text
- dim int
- vec vector

## relations
- id uuid pk
- src uuid
- dst uuid
- kind text
- payload jsonb

## sets
- id uuid pk
- name text
- payload jsonb

## membership
- set_id uuid fk→sets(id)
- object_id uuid fk→objects(id)
- role text
- payload jsonb

## decisions
- id uuid pk
- object_id uuid fk→objects(id)
- key text
- value jsonb
- created_at timestamptz default now()

## audit
- id uuid pk
- object_id uuid nullable
- agent text
- action text
- ts timestamptz default now()
- trace_id text
- details jsonb

## indexes
- GIN on objects.search_vector
- ivfflat/hnsw on embeddings.vec (pgvector)
- helpful btree indexes on (object_id), (key), (set_id)
