"""HAR-04: permit governed deletion-receipt cleanup reconciliation."""

from typing import Sequence, Union

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1a4b7c9e2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('app.heimdal_retention_reconcile', true) = 'true' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    raise RuntimeError("HAR-04 cleanup reconciliation is forward-only")
