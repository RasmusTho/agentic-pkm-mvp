import os
from alembic import op
import sqlalchemy as sa

revision = "202510241200"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    enable_vec = os.environ.get("ENABLE_VECTOR", "0") == "1"
    if enable_vec:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS objects(
      id UUID PRIMARY KEY,
      kind TEXT,
      source_ref TEXT,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS chunks(
      id UUID PRIMARY KEY,
      object_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      idx INTEGER NOT NULL,
      offset_start INTEGER NOT NULL,
      offset_end INTEGER NOT NULL,
      text TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS embeddings(
      id UUID PRIMARY KEY,
      object_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      chunk_id UUID REFERENCES chunks(id) ON DELETE CASCADE,
      provider TEXT DEFAULT 'mock',
      dim INTEGER NOT NULL DEFAULT 1536,
      embedding VECTOR,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS relations(
      id UUID PRIMARY KEY,
      src_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      dst_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      type TEXT NOT NULL,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS sets(
      id UUID PRIMARY KEY,
      name TEXT UNIQUE NOT NULL,
      meta JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS membership(
      id UUID PRIMARY KEY,
      set_id UUID NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
      object_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    )
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS decisions(
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      object_id UUID NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
      agent TEXT,
      kind TEXT,
      key TEXT NOT NULL,
      value JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    )
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS agent TEXT")
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS kind TEXT")
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()")

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS audit(
      id UUID PRIMARY KEY,
      object_id UUID REFERENCES objects(id) ON DELETE SET NULL,
      agent TEXT NOT NULL,
      action TEXT NOT NULL,
      ts TIMESTAMPTZ NOT NULL DEFAULT now(),
      trace_id TEXT,
      details JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_objects_payload ON objects USING GIN ((payload::jsonb) jsonb_path_ops)")
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='chunks' AND column_name='idx'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_chunks_object_idx ON public.chunks(object_id, idx)';
  ELSIF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='chunks' AND column_name='position'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_chunks_object_position ON public.chunks(object_id, position)';
  ELSE
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_chunks_object ON public.chunks(object_id)';
  END IF;
END$$;
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_object ON embeddings(object_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_relations_src ON relations(src_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_relations_dst ON relations(dst_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_membership_set ON membership(set_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_membership_object ON membership(object_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_decisions_object ON decisions(object_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_object ON audit(object_id)")

    if enable_vec:
        op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_vec ON embeddings USING ivfflat (embedding)")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec")
    op.execute("DROP INDEX IF EXISTS ix_audit_object")
    op.execute("DROP INDEX IF EXISTS ix_decisions_object")
    op.execute("DROP INDEX IF EXISTS ix_membership_object")
    op.execute("DROP INDEX IF EXISTS ix_membership_set")
    op.execute("DROP INDEX IF EXISTS ix_relations_dst")
    op.execute("DROP INDEX IF EXISTS ix_relations_src")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_object")
    op.execute("DROP INDEX IF EXISTS ix_chunks_object_idx")
    op.execute("DROP INDEX IF EXISTS ix_objects_payload")
    op.execute("DROP TABLE IF EXISTS audit")
    op.execute("DROP TABLE IF EXISTS decisions")
    op.execute("DROP TABLE IF EXISTS membership")
    op.execute("DROP TABLE IF EXISTS sets")
    op.execute("DROP TABLE IF EXISTS relations")
    op.execute("DROP TABLE IF EXISTS embeddings")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS objects")
