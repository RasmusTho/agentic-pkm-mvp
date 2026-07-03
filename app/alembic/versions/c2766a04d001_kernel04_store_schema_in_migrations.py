"""KERNEL-04 (#2766): store_* / vector_index_meta schema moves into Alembic.

Creates the five store tables exactly as `app/stores/pg.py::_ensure_tables()`
produced them (including the `store_vector_index` identity columns
`dim`/`model`/`provider`/`normalize` and the `vector_index_meta` singleton
shape). `IF NOT EXISTS` semantics: existing environments no-op, with the
column-level `ALTER ... ADD COLUMN IF NOT EXISTS` statements covering tables
created before the identity columns existed. No data movement.

Parity with `_ensure_tables()` is asserted by
`tests/migrations/test_store_schema_parity.py`.

Forward-only: the repo posture has no downgrade path for schema-owning
migrations (see docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md).
"""

from alembic import op

# Alembic identifiers
revision = "c2766a04d001"
down_revision = "5b8ff54bed0f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_objects (
            object_id UUID PRIMARY KEY,
            kind TEXT NOT NULL,
            source_ref TEXT,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_vector_index (
            object_id UUID PRIMARY KEY,
            kind TEXT NOT NULL,
            source_ref TEXT,
            payload JSONB NOT NULL,
            embedding DOUBLE PRECISION[] NOT NULL,
            dim INTEGER NOT NULL,
            model TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_relations (
            src_id UUID NOT NULL,
            dst_id UUID NOT NULL,
            rel TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (src_id, dst_id, rel)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS store_relation_memberships (
            src_id UUID NOT NULL,
            rel TEXT NOT NULL,
            value TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (src_id, rel, value)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_index_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            identity_json TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Environments whose store_vector_index predates the identity columns:
    # add them exactly as the bootstrap ALTERs did (nullable; the identity
    # data backfill lives in app/stores/pg.py::_backfill_identity_columns and
    # intentionally stays runtime-side — no data movement in this migration).
    op.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS dim INTEGER")
    op.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS provider TEXT")
    op.execute("ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS normalize BOOLEAN")


def downgrade() -> None:
    raise RuntimeError(
        "KERNEL-04 store-schema migration is forward-only; the store tables are "
        "the durable PDM substrate and are never dropped by downgrade."
    )
