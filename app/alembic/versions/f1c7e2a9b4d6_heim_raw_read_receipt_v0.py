"""HEIM (#3027): Gated raw-read receipt store v0 -- allowlist-gated read audit trail.

Slice A7 of Epic #3019 (Heimdal v1). Creates the append-only receipt table
backing `app/heimdal/raw_read_gate.py`, the gated read path over the raw
store built by A6 (`app/heimdal/raw_store.py`, migration `d5a8e2f1b6c3`):

- `heimdal_raw_read_receipt`: append-only record of every successful raw
  read (who: `reader`; what: `raw_ref` + `content_identity`, never
  `source_path`; when: `read_at`; why: `purpose`). Same HEIM-1 discipline
  as the raw record table itself (migration `d5a8e2f1b6c3`) and the
  observation log / consent ledger before it: a row is never updated or
  deleted, enforced by an identical append-only trigger.
- This is the durable half of the HEIM-5 interim gate
  (`docs/HEIMDAL/FABLE_COMPANION.md` §11#6 / "heim_policy_gated_raw_access"):
  a read is refused unless the caller passes the allowlist
  (`app.heimdal.raw_read_gate.resolve_read_allowlist`), and every read that
  is NOT refused writes exactly one row here in the same call that returns
  plaintext. Full CrossScopeFlow grant evaluation replacing the allowlist
  check is a declared v2 gap; this receipt contract does not change when
  that lands.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM-1 precedent: schema-
owning migrations in this repo have no downgrade path for their tables.

Revision ID: f1c7e2a9b4d6
Revises: d5a8e2f1b6c3
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "f1c7e2a9b4d6"
down_revision: Union[str, None] = "d5a8e2f1b6c3"
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
        CREATE TABLE IF NOT EXISTS heimdal_raw_read_receipt (
            id UUID PRIMARY KEY,
            raw_ref TEXT NOT NULL,
            content_identity TEXT NOT NULL,
            reader TEXT NOT NULL,
            purpose TEXT NOT NULL,
            read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_read_receipt_seq_idx "
        "ON heimdal_raw_read_receipt (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_read_receipt_raw_ref_idx "
        "ON heimdal_raw_read_receipt (raw_ref)"
    )

    # HEIM-1: append-only truth, enforced at the database level (defense in
    # depth on top of the Python store never exposing update/delete) --
    # identical pattern to heimdal_raw_record / heimdal_observation_log /
    # heimdal_consent_grant.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_read_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_read_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_raw_read_receipt_no_update ON heimdal_raw_read_receipt"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_raw_read_receipt_no_update
        BEFORE UPDATE OR DELETE ON heimdal_raw_read_receipt
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_read_receipt_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM raw-read-receipt migration is forward-only; the receipt log is the "
        "durable audit trail for gated raw reads and is never dropped by downgrade."
    )
