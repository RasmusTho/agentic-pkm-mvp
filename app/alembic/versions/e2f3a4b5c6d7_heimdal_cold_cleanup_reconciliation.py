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
        CREATE OR REPLACE FUNCTION heimdal_raw_cleanup_queue_is_subsequence(
            old_payload jsonb, new_payload jsonb
        ) RETURNS boolean AS $$
        DECLARE
            old_refs text[] := ARRAY(
                SELECT jsonb_array_elements_text(COALESCE(old_payload, '[]'::jsonb))
            );
            new_ref text;
            old_index integer := 1;
            old_length integer := COALESCE(array_length(old_refs, 1), 0);
        BEGIN
            FOR new_ref IN SELECT jsonb_array_elements_text(COALESCE(new_payload, '[]'::jsonb)) LOOP
                WHILE old_index <= old_length AND old_refs[old_index] <> new_ref LOOP
                    old_index := old_index + 1;
                END LOOP;
                IF old_index > old_length THEN
                    RETURN false;
                END IF;
                old_index := old_index + 1;
            END LOOP;
            RETURN true;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE STRICT;

        CREATE OR REPLACE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('app.heimdal_retention_reconcile', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.content_identity IS NOT DISTINCT FROM OLD.content_identity
               AND NEW.reason IS NOT DISTINCT FROM OLD.reason
               AND NEW.retention_window_days IS NOT DISTINCT FROM OLD.retention_window_days
               AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence
               AND (NEW.payload - 'cold_cleanup_location_refs')
                   IS NOT DISTINCT FROM (OLD.payload - 'cold_cleanup_location_refs')
               AND heimdal_raw_cleanup_queue_is_subsequence(
                   OLD.payload->'cold_cleanup_location_refs',
                   NEW.payload->'cold_cleanup_location_refs'
               ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    raise RuntimeError("HAR-04 cleanup reconciliation is forward-only")
