"""HAR-05: converge consent, archive, and retirement authority.

Revision ID: a9d7c5e3b1f0
Revises: f4b6c8d0e2a1
Create Date: 2026-08-22 00:00:00.000000

This forward-only revision is intentionally the single migration boundary for
the consent -> retention -> archive -> cleanup mechanism repaired by #3851.
The first dependency is a many-grant association for every exact raw
generation; later statements in this same revision bind representation and
cleanup generations to the shared retirement fence.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a9d7c5e3b1f0"
down_revision: Union[str, None] = "f4b6c8d0e2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute("LOCK TABLE heimdal_raw_record IN SHARE ROW EXCLUSIVE MODE")
    op.execute("LOCK TABLE heimdal_raw_liveness_generation IN SHARE ROW EXCLUSIVE MODE")
    op.execute("LOCK TABLE heimdal_raw_representation IN SHARE ROW EXCLUSIVE MODE")
    op.execute("LOCK TABLE heimdal_raw_deletion_receipt IN SHARE ROW EXCLUSIVE MODE")
    op.execute("LOCK TABLE heimdal_raw_retention_claim IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        DO $heimdal_archive_identity_preflight$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM heimdal_raw_representation
                WHERE storage_kind = 'encrypted_local_cold'
                  AND location_ref !~ '^heimloc:cold:[0-9a-f]{64}:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'cold representation lacks durable archive identity',
                    HINT = 'Reconcile the unbound cold location before retrying the migration.';
            END IF;
        END
        $heimdal_archive_identity_preflight$;

        DO $heimdal_cleanup_binding_preflight$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_deletion_receipt
                WHERE jsonb_array_length(
                    COALESCE(payload->'cold_cleanup_location_refs', '[]'::jsonb)
                ) > 0
                  AND (
                      jsonb_typeof(payload->'cold_cleanup_archive_bindings')
                          IS DISTINCT FROM 'object'
                      OR EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements_text(
                              payload->'cold_cleanup_location_refs'
                          ) AS queued(location_ref)
                          WHERE jsonb_typeof(
                              payload->'cold_cleanup_archive_bindings'
                                  ->queued.location_ref
                          ) IS DISTINCT FROM 'object'
                             OR payload->'cold_cleanup_archive_bindings'
                                  ->queued.location_ref->>'archive_token'
                                  !~ '^[0-9a-f]{64}$'
                             OR payload->'cold_cleanup_archive_bindings'
                                  ->queued.location_ref->>'archive_generation'
                                  !~ '^[0-9a-f]{64}$'
                             OR payload->'cold_cleanup_archive_bindings'
                                  ->queued.location_ref->>'raw_generation'
                                  !~ '^[1-9][0-9]*$'
                             OR payload->'cold_cleanup_archive_bindings'
                                  ->queued.location_ref->>'representation_id'
                                  !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                             OR queued.location_ref <> concat(
                                  'heimloc:cold:',
                                  payload->'cold_cleanup_archive_bindings'
                                      ->queued.location_ref->>'archive_token',
                                  ':',
                                  payload->'cold_cleanup_archive_bindings'
                                      ->queued.location_ref->>'representation_id'
                             )
                      )
                  )
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'pending cold cleanup lacks durable archive binding',
                    HINT = 'Reconcile the original verified archive before retrying the migration.';
            END IF;
        END
        $heimdal_cleanup_binding_preflight$;
        """
    )
    op.execute(
        "ALTER TABLE heimdal_raw_liveness_generation "
        "ADD CONSTRAINT heimdal_raw_liveness_generation_record_generation_uq "
        "UNIQUE (record_id, generation)"
    )
    op.execute(
        """
        CREATE TABLE heimdal_raw_consent_association (
            record_id uuid NOT NULL
                REFERENCES heimdal_raw_record(id) ON DELETE CASCADE,
            generation integer NOT NULL,
            grant_ref text NOT NULL CHECK (btrim(grant_ref) <> ''),
            admitted_at timestamptz NOT NULL,
            legacy_lineage_ambiguous boolean NOT NULL DEFAULT false,
            sequence bigserial NOT NULL,
            PRIMARY KEY (record_id, generation, grant_ref),
            FOREIGN KEY (record_id, generation)
                REFERENCES heimdal_raw_liveness_generation(record_id, generation)
                ON DELETE RESTRICT
        );
        CREATE INDEX heimdal_raw_consent_association_grant_idx
            ON heimdal_raw_consent_association (grant_ref, sequence);

        INSERT INTO heimdal_raw_consent_association (
            record_id, generation, grant_ref, admitted_at, legacy_lineage_ambiguous
        )
        SELECT r.id, g.generation, r.consent->>'grant_ref', r.ingested_at, true
        FROM heimdal_raw_record AS r
        JOIN heimdal_raw_liveness_generation AS g ON g.record_id = r.id
        WHERE jsonb_typeof(r.consent->'grant_ref') = 'string'
          AND btrim(r.consent->>'grant_ref') <> ''
        ORDER BY r.sequence;

        DO $heimdal_consent_association_backfill$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_record AS r
                JOIN heimdal_raw_liveness_generation AS g ON g.record_id = r.id
                LEFT JOIN heimdal_raw_deletion_tombstone AS t ON t.record_id = r.id
                LEFT JOIN heimdal_raw_consent_association AS a
                  ON a.record_id = r.id AND a.generation = g.generation
                WHERE t.record_id IS NULL
                GROUP BY r.id, g.generation
                HAVING count(a.grant_ref) = 0
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'active raw generation lacks durable consent association',
                    HINT = 'Repair uncorrelated consent metadata and rerun the migration.';
            END IF;
        END
        $heimdal_consent_association_backfill$;

        CREATE OR REPLACE FUNCTION heimdal_raw_consent_association_reject_mutation()
        RETURNS trigger AS $$
        DECLARE
            authority_identity text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.legacy_lineage_ambiguous
                   AND current_setting('app.heimdal_legacy_lineage_backfill', true)
                       IS DISTINCT FROM 'true' THEN
                    RAISE EXCEPTION
                        'legacy lineage ambiguity is migration-only authority';
                END IF;
                SELECT content_identity INTO authority_identity
                FROM heimdal_raw_liveness_generation
                WHERE record_id = NEW.record_id AND generation = NEW.generation;
                IF authority_identity IS NULL THEN
                    RAISE EXCEPTION
                        'consent association has no matching raw generation';
                END IF;
                PERFORM pg_advisory_xact_lock(hashtextextended(authority_identity, 0));
                IF EXISTS (
                    SELECT 1 FROM heimdal_raw_retention_claim
                    WHERE record_id = NEW.record_id
                ) OR EXISTS (
                    SELECT 1 FROM heimdal_raw_deletion_tombstone
                    WHERE record_id = NEW.record_id
                ) THEN
                    RAISE EXCEPTION
                        'consent association cannot admit a retiring raw generation';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE'
               AND current_setting('app.heimdal_retention_bypass', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM heimdal_raw_deletion_tombstone
                   WHERE record_id = OLD.record_id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'heimdal_raw_consent_association is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER heimdal_raw_consent_association_no_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON heimdal_raw_consent_association
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_consent_association_reject_mutation();
        """
    )
    op.execute(
        """
        ALTER TABLE heimdal_raw_representation
            ADD COLUMN raw_generation integer,
            ADD COLUMN archive_token text,
            ADD COLUMN archive_generation text;

        SELECT set_config('app.heimdal_representation_activation', 'true', true);
        UPDATE heimdal_raw_representation AS p
        SET raw_generation = g.generation
        FROM heimdal_raw_liveness_generation AS g
        WHERE g.record_id = p.record_id;

        UPDATE heimdal_raw_representation
        SET archive_token = substring(
            location_ref FROM '^heimloc:cold:([0-9a-f]{64}):'
        )
        WHERE storage_kind = 'encrypted_local_cold';

        DO $heimdal_legacy_claim_preflight$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_representation AS p
                JOIN heimdal_raw_retention_claim AS c ON c.record_id = p.record_id
                WHERE p.storage_kind = 'encrypted_local_cold'
                  AND p.archive_generation IS NULL
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'legacy cold representation has an active retention claim',
                    HINT = 'Drain governed retention claims on the HAR-04 schema before retrying HAR-05 migration.';
            END IF;
        END
        $heimdal_legacy_claim_preflight$;

        DO $heimdal_legacy_reservation_preflight$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_representation AS p
                WHERE p.storage_kind = 'encrypted_local_cold'
                  AND p.active = false
                  AND p.archive_generation IS NULL
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'legacy inactive cold reservation lacks archive generation',
                    HINT = 'Repair or remove the orphaned HAR-04 reservation and rerun the HAR-05 migration.';
            END IF;
        END
        $heimdal_legacy_reservation_preflight$;

        DO $heimdal_representation_generation_backfill$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM heimdal_raw_representation
                WHERE raw_generation IS NULL
            ) THEN
                RAISE EXCEPTION
                    'raw representation lacks a correlated liveness generation';
            END IF;
        END
        $heimdal_representation_generation_backfill$;

        ALTER TABLE heimdal_raw_representation
            ALTER COLUMN raw_generation SET NOT NULL,
            ADD CONSTRAINT heimdal_raw_representation_generation_fk
                FOREIGN KEY (record_id, raw_generation)
                REFERENCES heimdal_raw_liveness_generation(record_id, generation)
                ON DELETE RESTRICT,
            ADD CONSTRAINT heimdal_raw_representation_archive_generation_check
                CHECK (
                    (
                        storage_kind = 'postgres_hot'
                        AND archive_token IS NULL
                        AND archive_generation IS NULL
                    )
                    OR (
                        storage_kind = 'encrypted_local_cold'
                        AND archive_token ~ '^[0-9a-f]{64}$'
                        AND (
                            archive_generation ~ '^[0-9a-f]{64}$'
                            OR archive_generation IS NULL
                        )
                        AND location_ref LIKE
                            'heimloc:cold:' || archive_token || ':%'
                    )
                ),
            ADD CONSTRAINT heimdal_raw_representation_cold_owner_check
                CHECK (
                    storage_kind <> 'encrypted_local_cold'
                    OR location_ref =
                        'heimloc:cold:' || archive_token || ':' || id::text
                );

        CREATE OR REPLACE FUNCTION heimdal_raw_representation_reject_mutation()
        RETURNS trigger AS $$
        DECLARE
            authority_identity text;
            authority_generation integer;
        BEGIN
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                SELECT content_identity, generation
                INTO authority_identity, authority_generation
                FROM heimdal_raw_liveness_generation
                WHERE record_id = NEW.record_id;
                IF authority_identity IS NULL
                   OR NEW.raw_generation IS DISTINCT FROM authority_generation THEN
                    RAISE EXCEPTION
                        'raw representation has no matching liveness generation';
                END IF;
                PERFORM pg_advisory_xact_lock(hashtextextended(authority_identity, 0));
                IF EXISTS (
                    SELECT 1 FROM heimdal_raw_retention_claim
                    WHERE record_id = NEW.record_id
                ) OR EXISTS (
                    SELECT 1 FROM heimdal_raw_deletion_tombstone
                    WHERE record_id = NEW.record_id
                ) THEN
                    RAISE EXCEPTION
                        'raw representation cannot mutate a retiring generation';
                END IF;
                IF NEW.storage_kind = 'encrypted_local_cold'
                   AND EXISTS (
                       SELECT 1 FROM heimdal_raw_deletion_receipt
                       WHERE COALESCE(
                           payload->'cold_cleanup_location_refs', '[]'::jsonb
                       ) ? NEW.location_ref
                   ) THEN
                    RAISE EXCEPTION
                        'cold location remains owned by pending governed cleanup';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    RETURN NEW;
                END IF;
            END IF;
            IF TG_OP = 'UPDATE'
               AND current_setting('app.heimdal_legacy_archive_reconcile', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
               AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
               AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
               AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
               AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
               AND NEW.raw_generation IS NOT DISTINCT FROM OLD.raw_generation
               AND NEW.archive_token IS NOT DISTINCT FROM OLD.archive_token
               AND OLD.archive_generation IS NULL
               AND NEW.archive_generation ~ '^[0-9a-f]{64}$'
               AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE'
               AND current_setting('app.heimdal_representation_activation', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
               AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
               AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
               AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
               AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
               AND NEW.raw_generation IS NOT DISTINCT FROM OLD.raw_generation
               AND NEW.archive_token IS NOT DISTINCT FROM OLD.archive_token
               AND NEW.archive_generation IS NOT DISTINCT FROM OLD.archive_generation
               AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE'
               AND current_setting('app.heimdal_retention_bypass', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM heimdal_raw_deletion_tombstone
                   WHERE record_id = OLD.record_id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'heimdal_raw_representation mutation is governed: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER heimdal_raw_representation_no_mutation
            ON heimdal_raw_representation;
        CREATE TRIGGER heimdal_raw_representation_no_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON heimdal_raw_representation
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_representation_reject_mutation();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HAR-05 consent associations are forward-only erasure authority; "
        "downgrade would silently lose grant coverage for deduplicated raw evidence."
    )
