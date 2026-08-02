CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- NOTE: this file is naively split on the statement separator by
-- app/db/db.py::ensure_schema and by scripts/run_migration.py, so no comment
-- here may contain that character.
--
-- file_state DDL is intentionally absent. Alembic revision c7f4b1a83d29
-- (MVR-05A0, #4543) is the sole production owner of the vault-sync file_state
-- table, its (vault_binding_id, path) primary key, and file_state_uuid_idx.
-- Its "path text PRIMARY KEY" predecessor lived here, outside the revision
-- chain, which is why no migration could reach it. Test fixtures keep
-- create-on-demand through the explicit STORE_SCHEMA_AUTOCREATE opt-in in
-- app/db/db.py. This bootstrap must never create or mutate it again.
--
-- objects.path is owned by the same revision for the same reason. It was
-- declared here three times (a pre-create ALTER, the CREATE TABLE column list,
-- and a post-create ALTER) while objects itself is created by Alembic
-- revision 202510241200.

CREATE TABLE IF NOT EXISTS public.agent_memories(
  id uuid PRIMARY KEY,
  run_id uuid NULL,
  layer text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_memories_created_at_idx ON public.agent_memories (created_at DESC);

CREATE TABLE IF NOT EXISTS public.objects(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uuid uuid,
  kind text NOT NULL,
  source_ref text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS id uuid;
ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS uuid uuid;
ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS source_ref text;

-- Backfill/migrate legacy schemas that used uuid as the only identifier.
UPDATE public.objects SET id = uuid WHERE id IS NULL AND uuid IS NOT NULL;
UPDATE public.objects SET id = gen_random_uuid() WHERE id IS NULL;
UPDATE public.objects SET uuid = id WHERE uuid IS NULL;

ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;
ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);
CREATE UNIQUE INDEX IF NOT EXISTS objects_uuid_idx ON public.objects(uuid);
CREATE INDEX IF NOT EXISTS objects_created_at_idx ON public.objects (created_at DESC);
CREATE INDEX IF NOT EXISTS objects_source_ref_idx ON public.objects (source_ref);

-- Outbox DDL is intentionally absent here. Alembic revision f3a1c9d2e4b7 is
-- the sole production owner of the canonical outbox table and its indexes.
-- This legacy bootstrap may create other compatibility schema, but it must
-- never create or mutate outbox before assert-only runtime startup.

DROP VIEW IF EXISTS public.view_objects_ready_for_projection;
DROP VIEW IF EXISTS public.view_objects_missing_review;
DROP VIEW IF EXISTS public.view_chunks_missing_embeddings;
DROP VIEW IF EXISTS public.view_objects_missing_chunks;
-- NOTE (SoT v5.5): keep this file limited to "always safe" schema bootstraps.
-- Legacy v4.x views depended on tables/columns that are not part of the v5.5 baseline
-- and caused startup failures in fresh DBs. The DROP statements above intentionally
-- remove any lingering legacy views without recreating them here.
