from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = "202510251300"
down_revision = "fe9a3607841f"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    conn.execute(
        text(
            """
            DELETE FROM membership
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY set_id, object_id ORDER BY id) AS rn
                    FROM membership
                ) dup
                WHERE dup.rn > 1
            )
            """
        )
    )
    op.create_unique_constraint(
        "uq_membership_set_object",
        "membership",
        ["set_id", "object_id"],
    )


def downgrade():
    op.drop_constraint("uq_membership_set_object", "membership", type_="unique")
