"""Decision Calibration CAL-01: rebuildable outcome-receipt projection.

The vault JSONL receipt log is canonical; this table is intentionally only a
projection and is uniquely keyed by the decision's stable UUID plus rung.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a3f9d1c6e2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_outcomes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            decision_object_id UUID NOT NULL,
            decision_uuid UUID NOT NULL,
            rung_index INTEGER NOT NULL CHECK (rung_index >= 0),
            outcome TEXT NOT NULL CHECK (
                outcome IN ('held', 'partly_held', 'did_not_hold', 'unknown_yet')
            ),
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (decision_uuid, rung_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS decision_outcomes_object_id_idx "
        "ON decision_outcomes (decision_object_id)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "decision outcome receipts are canonical vault evidence and their projection "
        "migration is forward-only; use receipt-log rebuild rather than destructive downgrade."
    )
