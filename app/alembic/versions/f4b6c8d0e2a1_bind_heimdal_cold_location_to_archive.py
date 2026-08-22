"""HAR-04: bind every cold location handle to its producing archive."""

from typing import Sequence, Union

from alembic import op

revision: str = "f4b6c8d0e2a1"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"

_BOUND_COLD_LOCATION_PATTERN = (
    r"^heimloc:cold:[0-9a-f]{64}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def upgrade() -> None:
    # HAR-04 was not production-authoritative before this revision, so there is
    # no safe archive identity to infer for an unbound cold row. Refuse instead
    # of guessing a root and turning later missing_ok cleanup into silent loss.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_representation
                WHERE storage_kind = 'encrypted_local_cold'
                  AND location_ref !~ '{_BOUND_COLD_LOCATION_PATTERN}'
            ) THEN
                RAISE EXCEPTION
                    'cold representation location lacks producing archive identity';
            END IF;
        END;
        $$;

        ALTER TABLE heimdal_raw_representation
        ADD CONSTRAINT heimdal_raw_representation_cold_location_bound_check
        CHECK (
            storage_kind <> 'encrypted_local_cold'
            OR location_ref ~ '{_BOUND_COLD_LOCATION_PATTERN}'
        );
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HAR-04 is forward-only: removing the archive binding would make "
        "cold reads and post-erasure cleanup ambiguous."
    )
