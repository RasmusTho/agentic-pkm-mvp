"""EROJ-03: durable preallocated split plans and complement checkpoints."""
from alembic import op

revision = "b7e3c9d5a1f2"
down_revision = "a9d7c5e3b1f0"
branch_labels = None
depends_on = None
reversibility = "forward-only"

_SPLIT_DDL = """
CREATE TABLE IF NOT EXISTS entity_register_split_operations (
    vault_identity TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    plan JSONB NOT NULL,
    plan_digest TEXT NOT NULL,
    checkpoints JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (vault_identity, operation_id)
)
"""
_SPLIT_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS entity_register_split_active_idx
    ON entity_register_split_operations (vault_identity) WHERE NOT completed
"""


def upgrade() -> None:
    op.execute(_SPLIT_DDL)
    op.execute(_SPLIT_INDEX_DDL)


def downgrade() -> None:
    raise RuntimeError("EROJ-03 split recovery evidence is durable; downgrade is unsupported")
