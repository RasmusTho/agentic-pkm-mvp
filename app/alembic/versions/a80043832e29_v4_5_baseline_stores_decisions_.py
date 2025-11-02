"""v4_5 baseline stores (decisions, embeddings, membership, read-models)"""
from alembic import op
import sqlalchemy as sa

revision = 'a80043832e29'
down_revision = '6841f6d42913'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS public.decisions(
      id uuid PRIMARY KEY,
      object_id uuid NOT NULL REFERENCES public.objects(id) ON DELETE CASCADE,
      agent text,
      kind text,
      key text NOT NULL,
      value jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS decisions_object_id_idx ON public.decisions(object_id);
    CREATE INDEX IF NOT EXISTS decisions_key_idx ON public.decisions(key);
    CREATE INDEX IF NOT EXISTS decisions_obj_key_created_idx ON public.decisions(object_id, key, created_at DESC);
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS public.membership(
      object_id uuid NOT NULL REFERENCES public.objects(id) ON DELETE CASCADE,
      set_id uuid NOT NULL REFERENCES public.objects(id) ON DELETE CASCADE,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(object_id, set_id)
    );
    CREATE INDEX IF NOT EXISTS membership_set_id_idx ON public.membership(set_id);
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS public.embeddings(
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      object_id uuid NOT NULL REFERENCES public.objects(id) ON DELETE CASCADE,
      chunk_id uuid REFERENCES public.chunks(id) ON DELETE CASCADE,
      provider text DEFAULT 'mock',
      dim integer NOT NULL DEFAULT 1536,
      embedding double precision[],
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (embedding IS NULL OR cardinality(embedding) = dim)
    );
    CREATE INDEX IF NOT EXISTS embeddings_object_id_idx ON public.embeddings(object_id);
    CREATE INDEX IF NOT EXISTS embeddings_chunk_id_idx ON public.embeddings(chunk_id);
    """)
    op.execute("""
    DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public'
      AND table_name='view_chunks_missing_embeddings'
      AND column_name='embedding_count'
  ) THEN
    EXECUTE 'ALTER VIEW public.view_chunks_missing_embeddings RENAME COLUMN embedding_count TO embedded_chunks';
  END IF;
END$$;
CREATE OR REPLACE VIEW public.view_chunks_missing_embeddings AS
    SELECT
      o.id::text AS object_id,
      COUNT(DISTINCT c.id) AS chunk_count,
      COALESCE((
        SELECT COUNT(*) FROM public.embeddings e
        WHERE e.object_id = o.id AND e.chunk_id IS NOT NULL
      ), 0) AS embedded_chunks
    FROM public.objects o
    LEFT JOIN public.chunks c ON c.object_id = o.id
    GROUP BY o.id
    HAVING COUNT(DISTINCT c.id) > COALESCE((
      SELECT COUNT(*) FROM public.embeddings e
      WHERE e.object_id = o.id AND e.chunk_id IS NOT NULL
    ), 0);
    """)
    op.execute("""
    DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public'
      AND table_name='view_objects_ready_for_projection'
      AND column_name='score'
  ) THEN
    EXECUTE 'ALTER VIEW public.view_objects_ready_for_projection RENAME COLUMN score TO type';
  END IF;
END$$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public'
      AND table_name='view_objects_ready_for_projection'
      AND column_name='score'
  ) THEN
    EXECUTE 'ALTER VIEW public.view_objects_ready_for_projection RENAME COLUMN score TO type';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname='public' AND viewname='view_objects_ready_for_projection'
  ) THEN
    EXECUTE 'DROP VIEW public.view_objects_ready_for_projection';
  END IF;
END$$;
CREATE VIEW public.view_objects_ready_for_projection AS
    SELECT
      d.object_id::text AS object_id,
      COALESCE(d.value->>'type','') AS type,
      COALESCE(d.value->>'trust','') AS trust,
      d.created_at
    FROM public.decisions d
    WHERE d.key = 'classification'
      AND COALESCE(d.value->>'type','') <> ''
      AND NOT EXISTS (
        SELECT 1 FROM public.membership m WHERE m.object_id = d.object_id
      );
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.latest_decision(p_object_id uuid, p_key text)
    RETURNS jsonb
    LANGUAGE sql
    AS $$
      SELECT value
      FROM public.decisions
      WHERE object_id = p_object_id AND key = p_key
      ORDER BY created_at DESC
      LIMIT 1
    $$;
    """)

def downgrade():
    op.execute("DROP FUNCTION IF EXISTS public.latest_decision(uuid, text);")
    op.execute("DROP VIEW IF EXISTS public.view_objects_ready_for_projection;")
    op.execute("DROP VIEW IF EXISTS public.view_chunks_missing_embeddings;")
    op.execute("DROP TABLE IF EXISTS public.embeddings;")
    op.execute("DROP TABLE IF EXISTS public.membership;")
    op.execute("DROP TABLE IF EXISTS public.decisions;")
