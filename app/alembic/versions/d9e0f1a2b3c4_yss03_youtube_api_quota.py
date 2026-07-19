"""YSS-03 (#3918): durable per-UTC-day YouTube Data API quota counter.

Creates the one channel-DB row per UTC day consumed by
``app.knowledge_acquisition.youtube_api_client.YouTubeQuotaStore``. Every Data
API request atomically increments ``spent``; a provider quota-family response
also latches ``exhausted`` for that UTC day. Channel isolation comes from the
existing DB-per-channel discipline (INV-YSS-7), so this table intentionally
carries no environment column.

The table is runtime-operational/rebuildable sync state, but silently dropping
it during downgrade would erase the operator's same-day quota safety signal.
Following the existing YSS migration posture, this migration is forward-only.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"

_TABLE = "youtube_api_quota_daily"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            quota_date DATE PRIMARY KEY,
            spent INTEGER NOT NULL DEFAULT 0,
            exhausted BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT youtube_api_quota_daily_spent_chk CHECK (spent >= 0)
        )
        """
    )
    # Test/bootstrap-created tables may predate the migration-owned constraint.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'youtube_api_quota_daily_spent_chk'
                  AND conrelid = '{_TABLE}'::regclass
            ) THEN
                ALTER TABLE {_TABLE}
                ADD CONSTRAINT youtube_api_quota_daily_spent_chk CHECK (spent >= 0);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-03 youtube_api_quota_daily migration is forward-only; dropping it would erase "
        "the current UTC day's quota safety state."
    )
