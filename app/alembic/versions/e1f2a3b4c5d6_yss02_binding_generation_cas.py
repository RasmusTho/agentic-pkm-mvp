"""YSS-02 (#3990): add durable account-binding generation CAS authority.

Existing databases may already be stamped past the original YSS-02 table
revision. This migration adds the positive monotonic generation required by
OAuth terminal-state recovery without deriving authority from wall-clock
``updated_at`` values. Existing rows begin at generation 1; every subsequent
service-layer state write advances the value atomically.

The binding registry is authority-bearing OAuth lifecycle state. Following its
original migration posture, this schema change is forward-only rather than
silently removing compare-and-set evidence during downgrade.

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-07-20 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"

_TABLE = "youtube_account_binding"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
        ADD COLUMN IF NOT EXISTS binding_generation BIGINT NOT NULL DEFAULT 1
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'youtube_account_binding_generation_chk'
                  AND conrelid = '{_TABLE}'::regclass
            ) THEN
                ALTER TABLE {_TABLE}
                ADD CONSTRAINT youtube_account_binding_generation_chk
                CHECK (binding_generation >= 1);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-02 binding-generation CAS migration is forward-only; removing it would erase "
        "durable terminal-state recovery authority."
    )
