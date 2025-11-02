from alembic import op
import sqlalchemy as sa

# Alembic identifiers
revision = "5b8ff54bed0f"
down_revision = "a80043832e29"
branch_labels = None
depends_on = None

def upgrade():
    # Släpp ev. gamla vyer först (säkert omdefinierade tidigare)
    op.execute("DROP VIEW IF EXISTS public.view_objects_ready_for_projection")
    op.execute("DROP VIEW IF EXISTS public.view_chunks_missing_embeddings")

    # Projekteringsvy: senaste klassificering som inte redan är medlem i något set
    op.execute("""
    CREATE VIEW public.view_objects_ready_for_projection AS
    SELECT
      d.object_id::text          AS object_id,
      COALESCE(d.value->>'type','')  AS type,
      COALESCE(d.value->>'trust','') AS trust,
      d.created_at
    FROM public.decisions d
    WHERE d.key = 'classification'
      AND COALESCE(d.value->>'type','') <> ''
      AND NOT EXISTS (
        SELECT 1 FROM public.membership m WHERE m.object_id = d.object_id
      );
    """)

    # Vy: objekt med chunkar som saknar embeddings (räknar per-chunk)
    op.execute("""
    CREATE VIEW public.view_chunks_missing_embeddings AS
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

    # Index som matchar frågorna vi kör
    op.execute("CREATE INDEX IF NOT EXISTS ix_decisions_object_key_created ON public.decisions(object_id, key, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_object_pos ON public.chunks(object_id, pos)")

    # Hjälpfunktion: hämta senaste beslutet för ett key
    op.execute("""
    CREATE OR REPLACE FUNCTION public.latest_decision(p_object_id uuid, p_key text)
    RETURNS jsonb LANGUAGE plpgsql AS $$
    DECLARE v jsonb;
    BEGIN
      SELECT d.value INTO v
      FROM public.decisions d
      WHERE d.object_id = p_object_id AND d.key = p_key
      ORDER BY d.created_at DESC
      LIMIT 1;
      RETURN v;
    END; $$;
    """)

def downgrade():
    op.execute("DROP FUNCTION IF EXISTS public.latest_decision(uuid, text)")
    op.execute("DROP INDEX IF EXISTS ix_chunks_object_pos")
    op.execute("DROP INDEX IF EXISTS ix_decisions_object_key_created")
    op.execute("DROP VIEW IF EXISTS public.view_chunks_missing_embeddings")
    op.execute("DROP VIEW IF EXISTS public.view_objects_ready_for_projection")
