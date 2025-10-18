"""baseline schema

Revision ID: 3ddfc7237248
Revises:
Create Date: 2025-01-04 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ddfc7237248"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name="items_pkey"),
    )
    op.create_index("ix_items_id", "items", ["id"], unique=False)
    op.create_index("ix_items_name", "items", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_items_name", table_name="items")
    op.drop_index("ix_items_id", table_name="items")
    op.drop_table("items")
