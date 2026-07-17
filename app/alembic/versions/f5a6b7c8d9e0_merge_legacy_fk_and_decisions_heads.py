"""Merge #3510 legacy-FK and #3488 decisions-schema migration heads.

Revision ID: f5a6b7c8d9e0
Revises: 7e4f2a1c9d30, e1d2c3b4a5f6

Both migrations were independently branched from the v4.5 baseline.  This
topology-only revision restores one Alembic head so ``alembic upgrade head``
applies both forward-only schema changes on every supported upgrade path.
"""

from typing import Sequence, Union


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = ("7e4f2a1c9d30", "e1d2c3b4a5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    """Record the joined migration topology; both parents own the schema work."""


def downgrade() -> None:
    raise RuntimeError(
        "#3510/#3488 merge is forward-only: downgrade requires an explicit reviewed recovery migration."
    )
