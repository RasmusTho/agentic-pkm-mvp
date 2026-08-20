"""HEIM/CDLM: generation-aware raw liveness, response leases, and tombstones.

Revision ID: c5d8a1e4f2b7
Revises: f8a05a9b0001
Create Date: 2026-08-20 00:00:00.000000

The revision is forward-only because the append-only tombstone and generation
history become the authority that distinguishes governed erasure from
unavailable raw state. Existing deletion receipts are promoted into generation
tombstones; active raw rows receive the next generation for their content.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c5d8a1e4f2b7"
down_revision: Union[str, None] = "f8a05a9b0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"

_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_ACTIVATION_GUARD_SETTING = "app.heimdal_representation_activation"


def _append_only(function_name: str, table_name: str, trigger_name: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{table_name} is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}()
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("LOCK TABLE heimdal_raw_record IN SHARE ROW EXCLUSIVE MODE")
    op.execute("LOCK TABLE heimdal_raw_deletion_receipt IN SHARE ROW EXCLUSIVE MODE")

    op.execute(
        """
        CREATE TABLE heimdal_raw_liveness_generation (
            content_identity text NOT NULL,
            generation integer NOT NULL CHECK (generation > 0),
            record_id uuid NOT NULL UNIQUE,
            raw_ref text NOT NULL UNIQUE CHECK (raw_ref LIKE 'heimraw:%'),
            activated_at timestamptz NOT NULL,
            sequence bigserial NOT NULL,
            PRIMARY KEY (content_identity, generation)
        )
        """
    )
    op.execute(
        "CREATE INDEX heimdal_raw_liveness_generation_record_idx "
        "ON heimdal_raw_liveness_generation (record_id)"
    )
    op.execute(
        """
        CREATE TABLE heimdal_raw_deletion_tombstone (
            id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            generation integer NOT NULL,
            record_id uuid NOT NULL UNIQUE,
            raw_ref text NOT NULL UNIQUE,
            deletion_receipt_id uuid NOT NULL UNIQUE
                REFERENCES heimdal_raw_deletion_receipt(id) ON DELETE RESTRICT,
            reason text NOT NULL,
            erased_at timestamptz NOT NULL,
            sequence bigserial NOT NULL,
            FOREIGN KEY (content_identity, generation)
                REFERENCES heimdal_raw_liveness_generation(content_identity, generation)
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX heimdal_raw_deletion_tombstone_identity_idx "
        "ON heimdal_raw_deletion_tombstone (content_identity, generation)"
    )
    op.execute(
        """
        CREATE TABLE heimdal_raw_response_lease (
            lease_id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            generation integer NOT NULL,
            record_id uuid NOT NULL,
            raw_ref text NOT NULL,
            issued_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
            sequence bigserial NOT NULL,
            FOREIGN KEY (content_identity, generation)
                REFERENCES heimdal_raw_liveness_generation(content_identity, generation)
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX heimdal_raw_response_lease_active_idx "
        "ON heimdal_raw_response_lease (record_id, expires_at)"
    )

    # Every historical governed deletion already has durable terminal evidence.
    # Preserve its ordering as the generation history for that content.
    op.execute(
        """
        WITH deleted AS (
            SELECT d.*,
                   row_number() OVER (
                       PARTITION BY d.content_identity
                       ORDER BY d.deleted_at, d.sequence, d.id
                   )::integer AS generation
            FROM heimdal_raw_deletion_receipt AS d
        )
        INSERT INTO heimdal_raw_liveness_generation (
            content_identity, generation, record_id, raw_ref, activated_at
        )
        SELECT content_identity, generation, record_id,
               'heimraw:' || record_id::text, deleted_at
        FROM deleted
        ORDER BY content_identity, generation
        """
    )
    op.execute(
        """
        INSERT INTO heimdal_raw_deletion_tombstone (
            id, content_identity, generation, record_id, raw_ref,
            deletion_receipt_id, reason, erased_at
        )
        SELECT gen_random_uuid(), g.content_identity, g.generation, g.record_id,
               g.raw_ref, d.id, d.reason, d.deleted_at
        FROM heimdal_raw_deletion_receipt AS d
        JOIN heimdal_raw_liveness_generation AS g ON g.record_id = d.record_id
        ORDER BY d.sequence
        """
    )

    # An active same-content reinsertion is a later generation. A prior receipt
    # remains bound to its old raw_ref and can never resurrect against this row.
    op.execute(
        """
        INSERT INTO heimdal_raw_liveness_generation (
            content_identity, generation, record_id, raw_ref, activated_at
        )
        SELECT r.content_identity,
               coalesce(max(g.generation), 0) + 1,
               r.id,
               'heimraw:' || r.id::text,
               r.ingested_at
        FROM heimdal_raw_record AS r
        LEFT JOIN heimdal_raw_liveness_generation AS g
          ON g.content_identity = r.content_identity
        GROUP BY r.id, r.content_identity, r.ingested_at
        ORDER BY r.sequence
        """
    )

    op.execute(
        """
        DO $raw_liveness_backfill$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_record AS r
                LEFT JOIN heimdal_raw_liveness_generation AS g ON g.record_id = r.id
                LEFT JOIN heimdal_raw_deletion_tombstone AS t ON t.record_id = r.id
                GROUP BY r.id
                HAVING count(g.record_id) <> 1 OR count(t.record_id) <> 0
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'raw liveness backfill is incomplete',
                    HINT = 'Repair raw/deletion receipt identity conflicts and rerun the migration.';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_deletion_receipt AS d
                LEFT JOIN heimdal_raw_deletion_tombstone AS t
                  ON t.deletion_receipt_id = d.id
                WHERE t.id IS NULL
            ) THEN
                RAISE EXCEPTION 'deletion receipt lacks governed liveness tombstone';
            END IF;
        END
        $raw_liveness_backfill$;
        """
    )

    _append_only(
        "heimdal_raw_liveness_generation_reject_mutation",
        "heimdal_raw_liveness_generation",
        "heimdal_raw_liveness_generation_no_mutation",
    )
    _append_only(
        "heimdal_raw_deletion_tombstone_reject_mutation",
        "heimdal_raw_deletion_tombstone",
        "heimdal_raw_deletion_tombstone_no_mutation",
    )
    _append_only(
        "heimdal_raw_response_lease_reject_mutation",
        "heimdal_raw_response_lease",
        "heimdal_raw_response_lease_no_mutation",
    )

    # A session setting is no longer enough: the exact generation's tombstone
    # must already exist in the same transaction before any bytes can be erased.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM heimdal_raw_deletion_tombstone
                   WHERE record_id = OLD.id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted '
                'outside the governed tombstone transaction', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_representation_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('{_ACTIVATION_GUARD_SETTING}', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
               AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
               AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
               AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
               AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
               AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE'
               AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM heimdal_raw_deletion_tombstone
                   WHERE record_id = OLD.record_id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'heimdal_raw_representation mutation is governed: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Raw-liveness generations, response leases, and deletion tombstones are "
        "forward-only authority; downgrade would make erased and unavailable "
        "indistinguishable and weaken the deletion fence."
    )
