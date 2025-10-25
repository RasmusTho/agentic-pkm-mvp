from alembic import op

revision = "202510251330"
down_revision = "202510251300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW view_objects_missing_chunks AS
        SELECT o.id::text AS object_id
        FROM objects o
        WHERE NOT EXISTS (
            SELECT 1 FROM chunks c WHERE c.object_id = o.id
        );
        """
    )

    op.execute(
        """
        CREATE VIEW view_chunks_missing_embeddings AS
        SELECT o.id::text AS object_id,
               COUNT(DISTINCT c.id) AS chunk_count,
               COALESCE(
                   (
                       SELECT COUNT(*) FROM embeddings e WHERE e.object_id = o.id
                   ),
                   0
               ) AS embedding_count
        FROM objects o
        JOIN chunks c ON c.object_id = o.id
        GROUP BY o.id
        HAVING COUNT(DISTINCT c.id) > COALESCE(
            (
                SELECT COUNT(*) FROM embeddings e WHERE e.object_id = o.id
            ),
            0
        );
        """
    )

    op.execute(
        """
        CREATE VIEW view_objects_missing_review AS
        SELECT o.id::text AS object_id
        FROM objects o
        WHERE NOT EXISTS (
            SELECT 1 FROM decisions d WHERE d.object_id = o.id AND d.key = 'review'
        );
        """
    )

    op.execute(
        """
        CREATE VIEW view_objects_ready_for_projection AS
        SELECT d.object_id::text AS object_id,
               COALESCE((d.value ->> 'score')::numeric, 0) AS score,
               COALESCE((d.value ->> 'threshold')::numeric, 0) AS threshold
        FROM decisions d
        WHERE d.key = 'evaluate'
          AND COALESCE((d.value ->> 'promote')::boolean, false) = true
          AND NOT EXISTS (
              SELECT 1
              FROM membership m
              WHERE m.object_id = d.object_id
          );
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS view_objects_ready_for_projection")
    op.execute("DROP VIEW IF EXISTS view_objects_missing_review")
    op.execute("DROP VIEW IF EXISTS view_chunks_missing_embeddings")
    op.execute("DROP VIEW IF EXISTS view_objects_missing_chunks")
