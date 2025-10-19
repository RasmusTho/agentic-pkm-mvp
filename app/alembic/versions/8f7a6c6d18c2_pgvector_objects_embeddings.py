"""Initialize pgvector objects/embeddings tables."""

from alembic import op

# revision identifiers, used by Alembic.
revision = "8f7a6c6d18c2"
down_revision = "3ddfc7237248"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS objects(
          id UUID PRIMARY KEY,
          kind TEXT,
          source_ref TEXT,
          ts TIMESTAMPTZ DEFAULT now(),
          payload JSONB,
          search_vector tsvector GENERATED ALWAYS AS (
            to_tsvector(
              'english',
              coalesce(payload->>'title', '') || ' ' ||
              coalesce(payload->>'text', '') || ' ' ||
              coalesce(payload->>'content', '')
            )
          ) STORED
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings(
          id UUID PRIMARY KEY,
          object_id UUID REFERENCES objects(id) ON DELETE CASCADE,
          model TEXT NOT NULL,
          dim INT NOT NULL,
          vec vector(1536)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_objects_payload
        ON objects
        USING GIN (payload jsonb_path_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_embeddings_vec
        ON embeddings
        USING ivfflat (vec vector_cosine_ops)
        WITH (lists=100)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_objects_search_vector
        ON objects
        USING GIN (search_vector)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW objects_search AS
        SELECT
          id AS object_id,
          kind,
          source_ref,
          ts,
          payload,
          search_vector
        FROM objects
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION search_ft(query_text text, k integer DEFAULT 10)
        RETURNS TABLE(object_id uuid, rank_ft real)
        LANGUAGE sql
        AS $$
        SELECT
          obj.id AS object_id,
          ts_rank_cd(obj.search_vector, plainto_tsquery('english', query_text)) AS rank_ft
        FROM objects AS obj
        WHERE query_text IS NOT NULL
          AND btrim(query_text) <> ''
          AND obj.search_vector @@ plainto_tsquery('english', query_text)
        ORDER BY rank_ft DESC
        LIMIT k
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hybrid_search(
          query_text text,
          query_embedding vector,
          k integer DEFAULT 10
        )
        RETURNS TABLE(object_id uuid, score double precision, payload jsonb)
        LANGUAGE plpgsql
        AS $$
        DECLARE
          k1 integer := 60;
          k2 integer := 60;
        BEGIN
          IF (query_embedding IS NULL) AND (query_text IS NULL OR btrim(query_text) = '') THEN
            RETURN;
          END IF;
          RETURN QUERY
          WITH ft AS (
            SELECT
              obj.id AS object_id,
              ts_rank_cd(
                obj.search_vector,
                plainto_tsquery('english', query_text)
              ) AS rank_ft,
              row_number() OVER (
                ORDER BY ts_rank_cd(
                  obj.search_vector,
                  plainto_tsquery('english', query_text)
                ) DESC
              ) - 1 AS rank_pos
            FROM objects obj
            WHERE query_text IS NOT NULL
              AND btrim(query_text) <> ''
              AND obj.search_vector @@ plainto_tsquery('english', query_text)
            ORDER BY rank_ft DESC
            LIMIT GREATEST(k * 4, 10)
          ),
          vec AS (
            SELECT
              emb.object_id,
              1 - (emb.vec <=> query_embedding) AS similarity,
              row_number() OVER (ORDER BY emb.vec <=> query_embedding) - 1 AS rank_pos
            FROM embeddings emb
            WHERE query_embedding IS NOT NULL
            ORDER BY emb.vec <=> query_embedding
            LIMIT GREATEST(k * 4, 10)
          ),
          combined AS (
            SELECT
              COALESCE(ft.object_id, vec.object_id) AS object_id,
              ft.rank_pos AS rank_ft,
              vec.rank_pos AS rank_vec,
              COALESCE(ft.rank_ft, 0) AS score_ft,
              COALESCE(vec.similarity, 0) AS score_vec
            FROM ft
            FULL OUTER JOIN vec USING (object_id)
          )
          SELECT
            c.object_id,
            (CASE WHEN c.rank_ft IS NOT NULL THEN 1.0 / (k1 + c.rank_ft) ELSE 0 END) +
            (CASE WHEN c.rank_vec IS NOT NULL THEN 1.0 / (k2 + c.rank_vec) ELSE 0 END) AS score,
            o.payload
          FROM combined c
          JOIN objects o ON o.id = c.object_id
          ORDER BY score DESC
          LIMIT k;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS hybrid_search(text, vector, integer)")
    op.execute("DROP FUNCTION IF EXISTS search_ft(text, integer)")
    op.execute("DROP VIEW IF EXISTS objects_search")
    op.execute("DROP INDEX IF EXISTS ix_objects_search_vector")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec")
    op.execute("DROP INDEX IF EXISTS ix_objects_payload")
    op.execute("DROP TABLE IF EXISTS embeddings")
    op.execute("DROP TABLE IF EXISTS objects")
