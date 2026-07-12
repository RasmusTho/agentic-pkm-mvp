"""#3329: rebuildable Standing Questions projection.

The vault Question note is canonical. This table is a query-only mirror and is
repopulated exclusively by ``app.standing_questions.projection``.

Revision ID: 4d1e0c9a3329
Revises: b7c8d9e0f1a2
"""
from typing import Sequence, Union

from alembic import op

revision: str = "4d1e0c9a3329"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS standing_questions (
            question_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'answered', 'closed')),
            created_at TIMESTAMPTZ NOT NULL,
            registered_via TEXT NOT NULL CHECK (registered_via IN ('capture_intent', 'explicit')),
            standing_answer_ref TEXT,
            candidate_answer_ref TEXT,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            last_matched_at TIMESTAMPTZ,
            last_refreshed_at TIMESTAMPTZ,
            source_path TEXT NOT NULL UNIQUE
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS standing_questions_open_idx ON standing_questions (status) WHERE status = 'open'")
    op.execute("CREATE INDEX IF NOT EXISTS standing_questions_scope_idx ON standing_questions (scope)")


def downgrade() -> None:
    raise RuntimeError(
        "Standing Questions projection migration is forward-only; deployments must not erase "
        "the derived table outside an explicit migration."
    )
