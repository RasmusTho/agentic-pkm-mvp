"""merge heads

Revision ID: fe9a3607841f
Revises: 202501140001, 202510241200
Create Date: 2025-10-24 13:39:24.087099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe9a3607841f'
down_revision: Union[str, None] = ('202501140001', '202510241200')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
