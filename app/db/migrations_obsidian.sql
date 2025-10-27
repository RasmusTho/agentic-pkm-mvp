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

CREATE VIEW public.view_objects_missing_chunks AS
SELECT o.id::text AS object_id
FROM public.objects o
WHERE NOT EXISTS (
    SELECT 1 FROM public.chunks c WHERE c.object_id = o.id
);

CREATE VIEW public.view_chunks_missing_embeddings AS
SELECT o.id::text AS object_id,
       COUNT(DISTINCT c.id) AS chunk_count,
       COALESCE(
           (
               SELECT COUNT(*) FROM public.embeddings e WHERE e.object_id = o.id
           ),
           0
       ) AS embedding_count
FROM public.objects o
JOIN public.chunks c ON c.object_id = o.id
GROUP BY o.id
HAVING COUNT(DISTINCT c.id) > COALESCE(
    (
        SELECT COUNT(*) FROM public.embeddings e WHERE e.object_id = o.id
    ),
    0
);

CREATE VIEW public.view_objects_missing_review AS
SELECT o.id::text AS object_id
FROM public.objects o
WHERE NOT EXISTS (
    SELECT 1 FROM public.decisions d
    WHERE d.object_id = o.id
      AND d.key = 'review'
);

CREATE VIEW public.view_objects_ready_for_projection AS
SELECT d.object_id::text AS object_id,
       COALESCE((d.value ->> 'score')::numeric, 0) AS score,
       COALESCE((d.value ->> 'threshold')::numeric, 0) AS threshold
FROM public.decisions d
WHERE d.key = 'evaluate'
  AND COALESCE((d.value ->> 'promote')::boolean, false) = true
  AND NOT EXISTS (
      SELECT 1
      FROM public.membership m
      WHERE m.object_id = d.object_id
  );
