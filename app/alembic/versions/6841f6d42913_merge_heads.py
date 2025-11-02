"""merge heads

Revision ID: 6841f6d42913
Revises: 202510241200, fe9a3607841f
Create Date: 2025-10-31 19:11:14.253666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6841f6d42913'
down_revision: Union[str, None] = ('202510241200', 'fe9a3607841f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
