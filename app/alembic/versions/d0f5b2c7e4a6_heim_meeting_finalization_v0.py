"""CDLM-08 (#4388): Meeting finalization receipt v0 — completeness made permanent.

Creates `heimdal_meeting_finalization_receipt`, backing
`app/heimdal/meeting_finalization.py`: one row per
`(session_id, state_sha256)` — the ledger completeness state a finalization is
idempotent over. A row is written only after the three Sources-zone artifacts
are materialized AND the `heimdal.meeting.finalized` event is committed; the
row IS the finalized acknowledgement (CDLM-01 ack-ordering family). Lineage:
`supersedes` names the prior state on post-close reconciliation; superseded
artifacts remain on disk.

Append-only (trigger below): a finalization acknowledgement is never edited or
deleted — re-derivation adds the next state's row.

Forward-only per the repo precedent: dropping this table would erase the only
durable record of which completeness state each permanent vault artifact was
finalized under.

Revision ID: d0f5b2c7e4a6
Revises: c9e4a1b6d3f5
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "d0f5b2c7e4a6"
down_revision: Union[str, None] = "c9e4a1b6d3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_finalization_receipt (
            session_id TEXT NOT NULL,
            state_sha256 TEXT NOT NULL,
            complete BOOLEAN NOT NULL,
            missing_seqs JSONB NOT NULL DEFAULT '[]'::jsonb,
            artifact_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
            supersedes TEXT,
            finalized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, state_sha256)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_finalization_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_meeting_finalization_receipt is append-only (CDLM-08): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_finalization_receipt_no_update "
        "ON heimdal_meeting_finalization_receipt"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_finalization_receipt_no_update
        BEFORE UPDATE OR DELETE ON heimdal_meeting_finalization_receipt
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_finalization_receipt_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "CDLM-08 finalization-receipt migration is forward-only; the receipt is the "
        "durable finalized acknowledgement (INV-CDLM-9) and is never dropped by "
        "downgrade."
    )
