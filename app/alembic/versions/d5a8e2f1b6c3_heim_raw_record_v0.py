"""HEIM (#3025): Raw evidence record store v0 -- encrypted-at-rest capture landing table.

Slice A6 of Epic #3019 (Heimdal v1). Creates the append-only raw-evidence
table backing `app/heimdal/raw_store.py`, the durable write target of the
voice-memo capture adapter (`app/heimdal/capture_adapter.py`):

- `heimdal_raw_record`: append-only store of encrypted raw evidence
  (`ciphertext`, `nonce`, `key_ref` -- see `app/heimdal/raw_store.py` module
  docstring for the encryption-at-rest scheme). Same HEIM-1 discipline as
  the observation log (migration `8b21e6a1f0c4`) and the consent ledger
  (migration `c4f7a1b2d9e3`): a row is never updated or deleted, enforced
  by an identical append-only trigger (defense in depth on top of the
  Python store exposing no update/delete API).
- Carries the provenance fields FABLE_COMPANION §1.1 requires stamped in
  the SAME durable write as the record (KERNEL-06 discipline):
  `content_identity` (hash of the raw evidence, the KAP-compatible join
  key), `capture_chain` (`["ios_voice_memos", "icloud_drive",
  "folder_watch"]` for v1), `sensor` (adapter id + version + device,
  T5 mitigation -- unregistered-source ingestion is refused before this
  table is ever written to), and `consent.grant_ref` (HEIM-3, stamped from
  `app.heimdal.consent_ledger.admit_raw_evidence`).
- `source_path` records the original watched-folder path for operator
  traceability; it is NOT the encryption key material and carries no
  secret. `ingested_at` and `sequence` support ordering/audit.

This does not touch `heimdal_observation_log` / `heimdal_consent_grant` --
the raw store is its own append-only table; the capture adapter reads an
active grant from the consent ledger and writes exactly one row here per
admitted memo (Out of scope for this slice per FABLE_COMPANION §11#6: the
gated *read* path over this table is `heimdal_raw_read_receipt`, migration
`f1c7e2a9b4d6`, slice A7, #3027).

Forward-only, following the KERNEL-04/KERNEL-05/HEIM-1 precedent: schema-
owning migrations in this repo have no downgrade path for their tables.

Revision ID: d5a8e2f1b6c3
Revises: c4f7a1b2d9e3
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "d5a8e2f1b6c3"
down_revision: Union[str, None] = "c4f7a1b2d9e3"
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
        CREATE TABLE IF NOT EXISTS heimdal_raw_record (
            id UUID PRIMARY KEY,
            content_identity TEXT NOT NULL,
            capture_chain JSONB NOT NULL,
            sensor JSONB NOT NULL,
            consent JSONB NOT NULL,
            ciphertext BYTEA NOT NULL,
            nonce BYTEA NOT NULL,
            key_ref TEXT NOT NULL,
            source_path TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_record_seq_idx "
        "ON heimdal_raw_record (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_record_content_identity_idx "
        "ON heimdal_raw_record (content_identity)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS heimdal_raw_record_content_identity_uq "
        "ON heimdal_raw_record (content_identity)"
    )

    # HEIM-1: append-only truth, enforced at the database level (defense in
    # depth on top of the Python store never exposing update/delete) --
    # identical pattern to heimdal_observation_log / heimdal_consent_grant.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_raw_record_no_update ON heimdal_raw_record"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_raw_record_no_update
        BEFORE UPDATE OR DELETE ON heimdal_raw_record
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_record_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM raw-record migration is forward-only; the raw store is the "
        "durable capture landing record and is never dropped by downgrade."
    )
