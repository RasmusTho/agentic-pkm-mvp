CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE IF EXISTS public.objects ADD COLUMN IF NOT EXISTS path text;

CREATE TABLE IF NOT EXISTS public.file_state (
  path text PRIMARY KEY,
  uuid text,
  fm_hash text,
  body_hash text,
  mtime timestamptz,
  last_seen timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS file_state_uuid_idx ON public.file_state(uuid);

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
  uuid uuid PRIMARY KEY,
  kind text NOT NULL,
  path text,
  source_ref text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS source_ref text;
ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS path text;
CREATE INDEX IF NOT EXISTS objects_created_at_idx ON public.objects (created_at DESC);
CREATE INDEX IF NOT EXISTS objects_source_ref_idx ON public.objects (source_ref);

CREATE TABLE IF NOT EXISTS public.outbox(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  topic text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz NULL,
  attempts int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_created_at_idx ON public.outbox (created_at DESC);
CREATE INDEX IF NOT EXISTS outbox_delivered_null_idx ON public.outbox ((delivered_at IS NULL));

DROP VIEW IF EXISTS public.view_objects_ready_for_projection;
DROP VIEW IF EXISTS public.view_objects_missing_review;
DROP VIEW IF EXISTS public.view_chunks_missing_embeddings;
DROP VIEW IF EXISTS public.view_objects_missing_chunks;
-- NOTE (SoT v5.5): keep this file limited to "always safe" schema bootstraps.
-- Legacy v4.x views depended on tables/columns that are not part of the v5.5 baseline
-- and caused startup failures in fresh DBs. The DROP statements above intentionally
-- remove any lingering legacy views without recreating them here.
