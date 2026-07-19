"""Merge the #3510 legacy-FK and YSS-04 Alembic heads.

Revision ID: c8d9e0f1a2b3
Revises: b7e8f9a0b1c2, b5c6d7e8f9a0

Both parent revisions are forward-only schema migrations. This revision owns
no schema operation; it restores a single Alembic head so a normal
``alembic upgrade head`` applies every reviewed migration exactly once.
"""

from typing import Sequence, Union


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = ("b7e8f9a0b1c2", "b5c6d7e8f9a0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    """Record the joined topology; each parent owns its schema changes."""


def downgrade() -> None:
    raise RuntimeError(
        "#3510/YSS-04 merge revision is forward-only; downgrade each reviewed parent "
        "through its own governed rollback path."
    )
