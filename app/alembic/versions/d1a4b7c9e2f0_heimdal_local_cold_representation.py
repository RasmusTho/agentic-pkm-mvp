"""HAR-04: permit verified encrypted local-cold representations."""

from typing import Sequence, Union

from alembic import op

revision: str = "d1a4b7c9e2f0"
down_revision: Union[str, None] = "c5d8a1e4f2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"


def upgrade() -> None:
    # The representation row remains the durable registry entry. The archive
    # manifest and encrypted bytes live on the already-verified cold volume.
    op.execute(
        "ALTER TABLE heimdal_raw_representation "
        "DROP CONSTRAINT IF EXISTS heimdal_raw_representation_storage_kind_check"
    )
    op.execute(
        "ALTER TABLE heimdal_raw_representation "
        "ADD CONSTRAINT heimdal_raw_representation_storage_kind_check "
        "CHECK (storage_kind IN ('postgres_hot', 'encrypted_local_cold'))"
    )


def downgrade() -> None:
    raise RuntimeError(
        "HAR-04 is forward-only: removing encrypted_local_cold would strand "
        "registered cold representations."
    )
