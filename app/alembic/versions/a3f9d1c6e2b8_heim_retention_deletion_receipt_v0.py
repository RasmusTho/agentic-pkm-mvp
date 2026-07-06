"""HEIM (#3032): Hard-retention deletion receipt store v0 + governed raw-delete exception.

Slice A12 of Epic #3019 (Heimdal v1). Creates the append-only deletion-
receipt table backing `app/heimdal/retention.py`'s hard-retention ops job,
and installs the ONE governed exception to `heimdal_raw_record`'s append-
only trigger (migration `d5a8e2f1b6c3`) that admits a hard delete under
D-RETENTION (Charter FIXED #7):

- `heimdal_raw_deletion_receipt`: append-only record of every hard-deleted
  raw record (what: `record_id` + `content_identity`; when: `deleted_at`;
  why: `reason` -- always ``"hard_retention_bound"`` in v1, the event-
  triggered decay model being a v2 contract-stub; `retention_window_days`
  names the bound in force at deletion time). Same HEIM-1 discipline as
  every other Heimdal table: a row is never updated or deleted, enforced by
  an identical append-only trigger -- the deletion receipt itself is never
  erased, only the raw evidence it attests to.
- `heimdal_raw_record_reject_mutation()` (owned by `d5a8e2f1b6c3`) is
  REPLACED here to admit exactly one exception: a DELETE issued while the
  session-local setting ``app.heimdal_retention_bypass`` is ``'true'`` in
  the same transaction. That setting is set (and only readable within that
  same connection/transaction) by `app.heimdal.raw_store.hard_delete_raw_record`
  immediately before the DELETE -- no other code path, migration, or ad hoc
  SQL client can set it, so the DB-level guarantee "no hard delete outside
  the governed job" holds independent of which code path issues the
  statement. UPDATE is never admitted under any guard -- only removal.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM-1 precedent: schema-
owning migrations in this repo have no downgrade path for their tables.

Revision ID: a3f9d1c6e2b8
Revises: f1c7e2a9b4d6
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a3f9d1c6e2b8"
down_revision: Union[str, None] = "f1c7e2a9b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_raw_deletion_receipt (
            id UUID PRIMARY KEY,
            record_id UUID NOT NULL,
            content_identity TEXT NOT NULL,
            reason TEXT NOT NULL,
            retention_window_days INTEGER NOT NULL,
            deleted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_deletion_receipt_seq_idx "
        "ON heimdal_raw_deletion_receipt (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_deletion_receipt_record_id_idx "
        "ON heimdal_raw_deletion_receipt (record_id)"
    )

    # HEIM-1: append-only truth for the receipt itself -- identical pattern
    # to every other Heimdal table. A deletion receipt is never itself
    # deleted or edited, even though it attests to a deletion.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_raw_deletion_receipt_no_update ON heimdal_raw_deletion_receipt"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_raw_deletion_receipt_no_update
        BEFORE UPDATE OR DELETE ON heimdal_raw_deletion_receipt
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        """
    )

    # D-RETENTION governed exception: replace heimdal_raw_record's
    # append-only trigger function (owned by d5a8e2f1b6c3) to admit exactly
    # one exception -- a DELETE issued under the session-local retention
    # bypass guard. CREATE OR REPLACE FUNCTION keeps the same trigger
    # binding (heimdal_raw_record_no_update) pointed at the updated body;
    # no DROP/CREATE TRIGGER needed since the function name is unchanged.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted '
                'outside the governed hard-retention job (D-RETENTION)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM retention-deletion-receipt migration is forward-only; the receipt log is "
        "the durable audit trail for hard-deleted raw evidence and is never dropped by "
        "downgrade, and reverting the trigger exception would silently re-widen or "
        "narrow the governed D-RETENTION delete path outside a reviewed migration."
    )
