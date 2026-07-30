"""CDLM-01 (#4384): Media-admission receipt store v0 -- the durable-acceptance answer.

Creates the append-only receipt table backing `app/heimdal/media_receipts.py`,
the client-visible half of the governed media ingress lane
(`app/heimdal/media_ingress.py`, `POST /api/heimdal/capture/media`):

- `heimdal_media_receipt`: one row per transfer identity
  `(capture_id, content_sha256)` (INV-CDLM-3), written only after the original
  is durably in `heimdal_raw_record` (migration `d5a8e2f1b6c3`) AND the
  `heimdal.capture.media.admitted` outbox event is committed. A row here is
  therefore the definition of durable acceptance (INV-CDLM-1): an HTTP 2xx
  without one would be a false receipt, the exact failure class this vertical
  exists to remove (#4369).
- `receipt_id` is the primary key and is *derived* (uuid5 over the identity
  pair, `app.heimdal.media_receipts.derive_receipt_id`), so a client resend
  after a lost response collides on the key instead of minting a second
  acknowledgement. The insert path uses `ON CONFLICT DO NOTHING`, never
  `DO UPDATE` -- the append-only trigger below rejects UPDATE.
- `capture_id` is indexed because reconnect recovery
  (`GET /api/heimdal/capture/receipts?capture_id=…`) is the query that
  distinguishes "lost response" from "never arrived". It carries the client's
  minted UUID for the governed lane and the content hash itself for a
  watched-folder admission with no sidecar `capture_id` ("content-hash keyed",
  per the vertical's partial-failure matrix).
- Same HEIM-1 discipline as `heimdal_raw_record` / `heimdal_raw_read_receipt` /
  `heimdal_observation_log` / `heimdal_consent_grant`: a row is never updated or
  deleted, enforced by an identical append-only trigger.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM-1 precedent: schema-owning
migrations in this repo have no downgrade path for their tables. Dropping this
table would destroy the only durable record of which captures were accepted,
which every downstream CDLM slice gates on.

Revision ID: e3c1a7f5d2b8
Revises: d9e0f1a2b3c4
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "e3c1a7f5d2b8"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
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
        CREATE TABLE IF NOT EXISTS heimdal_media_receipt (
            receipt_id TEXT PRIMARY KEY,
            capture_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            raw_ref TEXT NOT NULL,
            kind TEXT NOT NULL,
            lane TEXT NOT NULL,
            admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            trace_id TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_media_receipt_seq_idx "
        "ON heimdal_media_receipt (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_media_receipt_capture_id_idx "
        "ON heimdal_media_receipt (capture_id)"
    )

    # HEIM-1: append-only truth, enforced at the database level (defense in
    # depth on top of the Python store never exposing update/delete) --
    # identical pattern to heimdal_raw_read_receipt / heimdal_raw_record.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_media_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_media_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_media_receipt_no_update ON heimdal_media_receipt"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_media_receipt_no_update
        BEFORE UPDATE OR DELETE ON heimdal_media_receipt
        FOR EACH ROW EXECUTE FUNCTION heimdal_media_receipt_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "CDLM-01 media-receipt migration is forward-only; the receipt table is the "
        "durable definition of accepted media (INV-CDLM-1) and is never dropped by "
        "downgrade."
    )
