from alembic import op
import sqlalchemy as sa
import uuid

revision = "fe9a3607841f"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "objects",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("uuid", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()")
        ),
    )
    op.create_index("objects_uuid_idx", "objects", ["uuid"])
    op.create_index("objects_kind_idx", "objects", ["kind"])

    op.create_table(
        "objects_embeddings",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
    )

def downgrade():
    op.drop_table("objects_embeddings")
    op.drop_index("objects_kind_idx", table_name="objects")
    op.drop_index("objects_uuid_idx", table_name="objects")
    op.drop_table("objects")
