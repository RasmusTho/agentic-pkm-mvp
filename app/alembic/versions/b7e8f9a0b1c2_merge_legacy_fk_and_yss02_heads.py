"""Merge the #3510 legacy-FK and YSS-02 Alembic heads.

Revision ID: b7e8f9a0b1c2
Revises: f5a6b7c8d9e0, a2f1c3e4d5b6

Both parent revisions are forward-only schema migrations.  This revision owns
no schema operation; it restores a single Alembic head so a normal
``alembic upgrade head`` applies every reviewed migration exactly once.
"""

from typing import Sequence, Union


revision: str = "b7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = ("f5a6b7c8d9e0", "a2f1c3e4d5b6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    """Record the joined topology; each parent owns its schema changes."""


def downgrade() -> None:
    raise RuntimeError(
        "#3510/YSS-02 topology merge is forward-only; downgrade requires an explicit "
        "reviewed recovery migration."
    )
