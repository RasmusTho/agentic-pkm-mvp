"""HEIM (#3039): Heimdal observation log + per-consumer cursor schema.

Slice A2 of Epic #3019 (Heimdal v1). Creates the two tables backing
`app/heimdal/observation_log.py` and `app/heimdal/cursor_store.py`:

- `heimdal_observation_log`: append-only canonical stream of published
  Heimdal observation events (FABLE_COMPANION §4.2). A trigger rejects any
  UPDATE/DELETE against the table at the database level (HEIM-1,
  append-only truth) -- independent of the Python API, which also exposes
  no update/delete method.
- `heimdal_observation_cursor`: one row per consumer, tracking that
  consumer's own read position. Consumers never share or affect each
  other's row.

This does **not** touch the existing `outbox` table (KERNEL-05,
`f3a1c9d2e4b7`) -- the Heimdal log reuses that table's envelope/idempotency
*pattern*, not its schema or rows (FABLE_COMPANION §4.3(a) explicitly
rejects folding this stream into `outbox`).

Forward-only, following the KERNEL-04/KERNEL-05 precedent: schema-owning
migrations in this repo have no downgrade path for their tables.

Revision ID: 8b21e6a1f0c4
Revises: f3a1c9d2e4b7
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "8b21e6a1f0c4"
down_revision: Union[str, None] = "f3a1c9d2e4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_observation_log (
            id UUID PRIMARY KEY,
            topic TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_observation_log_seq_idx "
        "ON heimdal_observation_log (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_observation_log_topic_idx "
        "ON heimdal_observation_log (topic)"
    )

    # HEIM-1: append-only truth, enforced at the database level (defense in
    # depth on top of the Python store never exposing update/delete).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_observation_log_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_observation_log is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_observation_log_no_update ON heimdal_observation_log"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_observation_log_no_update
        BEFORE UPDATE OR DELETE ON heimdal_observation_log
        FOR EACH ROW EXECUTE FUNCTION heimdal_observation_log_reject_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_observation_cursor (
            consumer_id TEXT PRIMARY KEY,
            position BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM observation-log migration is forward-only; the log is the canonical "
        "Heimdal<->Mimer seam and is never dropped by downgrade."
    )
