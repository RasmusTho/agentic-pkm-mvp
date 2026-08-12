"""HAR-02 (#3848): split immutable raw identity from encrypted representations.

The legacy ``heimdal_raw_record`` row combines immutable identity/provenance
with one Postgres-hot ciphertext. That shape cannot represent a verified copy
or later location change without deleting the identity behind the opaque
``raw_ref``. This forward-only revision creates a registry of encrypted
representations, backfills every legacy record as one active ``postgres_hot``
representation, proves the backfill is complete, and only then removes the
inline encrypted columns from the identity table.

The entire revision is transactional on PostgreSQL. A failed backfill leaves
the legacy table and its readable bytes untouched, and rerunning the revision
restarts safely. The deterministic initial representation id/location handle
also makes the insert idempotent. No cold locator is created by this revision.

Revision ID: e7b4c9d2a6f1
Revises: e6c4a2b8d1f3
Create Date: 2026-08-12 00:00:00.000000
"""

import hashlib
import os
from typing import Sequence, Union

from alembic import op
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

revision: str = "e7b4c9d2a6f1"
down_revision: Union[str, None] = "e6c4a2b8d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reversibility: str = "forward-only"

_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_ACTIVATION_GUARD_SETTING = "app.heimdal_representation_activation"
_KEY_ENV_VAR = "HEIMDAL_RAW_STORE_KEY"


def _verify_legacy_content_identities() -> None:
    """Fail before backfill unless every legacy ciphertext proves its identity.

    The verification uses the same process key and canonical digest contract as
    runtime registration/read.  It runs on Alembic's transaction connection
    before any representation is inserted or activated.  Raising here leaves
    the legacy schema and inline encrypted bytes intact for a corrected retry.
    """
    connection = op.get_bind()
    # Hold out concurrent legacy inserts/deletes between the verification
    # snapshot and the later INSERT ... SELECT/drop. PostgreSQL keeps this
    # table lock until Alembic commits or rolls the whole revision back.
    connection.execute(text("LOCK TABLE heimdal_raw_record IN SHARE MODE"))
    rows = connection.execute(
        text(
            """
            SELECT content_identity, ciphertext, nonce
            FROM heimdal_raw_record
            ORDER BY id
            """
        )
    )
    key: bytes | None = None
    try:
        for row in rows:
            try:
                if key is None:
                    raw_key = os.environ.get(_KEY_ENV_VAR, "")
                    key = bytes.fromhex(raw_key)
                    if len(key) != 32:
                        raise ValueError("raw-store key must decode to exactly 32 bytes")
                plaintext = AESGCM(key).decrypt(
                    bytes(row.nonce or b""),
                    bytes(row.ciphertext or b""),
                    None,
                )
                digest = hashlib.sha256(plaintext).hexdigest()
                if str(row.content_identity) not in {digest, f"sha256:{digest}"}:
                    raise ValueError("legacy plaintext does not match content identity")
            except Exception as exc:
                raise RuntimeError(
                    "HAR-02 legacy raw representation identity verification failed; "
                    "legacy schema and encrypted bytes remain unchanged. Correct the key or "
                    "legacy identity/data and rerun alembic upgrade head."
                ) from exc
    finally:
        rows.close()


def upgrade() -> None:
    _verify_legacy_content_identities()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_raw_representation (
            id uuid PRIMARY KEY,
            record_id uuid NOT NULL
                REFERENCES heimdal_raw_record(id) ON DELETE RESTRICT,
            storage_kind text NOT NULL
                CHECK (storage_kind IN ('postgres_hot')),
            location_ref text NOT NULL UNIQUE
                CHECK (location_ref LIKE 'heimloc:%'),
            ciphertext bytea,
            nonce bytea,
            key_ref text,
            active boolean NOT NULL DEFAULT false,
            registered_at timestamptz NOT NULL DEFAULT now(),
            sequence bigserial NOT NULL
        )
        """
    )

    # Deterministic backfill: the legacy identity UUID becomes the initial
    # representation UUID and opaque internal location handle. This is not a
    # path and does not fabricate a cold/archive location.
    op.execute(
        """
        INSERT INTO heimdal_raw_representation (
            id, record_id, storage_kind, location_ref,
            ciphertext, nonce, key_ref, active, registered_at
        )
        SELECT r.id, r.id, 'postgres_hot', 'heimloc:' || r.id::text,
               r.ciphertext, r.nonce, r.key_ref, true, r.ingested_at
        FROM heimdal_raw_record AS r
        ON CONFLICT (id) DO NOTHING
        """
    )

    # Fail before removing any legacy bytes unless every identity resolves to
    # exactly one complete active hot representation. Any exception rolls the
    # revision back, so the legacy reader remains usable and a rerun resumes
    # from the unchanged old shape.
    op.execute(
        """
        DO $heimdal_raw_backfill_preflight$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM heimdal_raw_record AS r
                LEFT JOIN heimdal_raw_representation AS p ON p.record_id = r.id
                GROUP BY r.id
                HAVING count(*) FILTER (WHERE p.active) <> 1
                    OR count(*) FILTER (
                        WHERE p.active
                          AND (
                            p.id IS DISTINCT FROM r.id
                            OR p.storage_kind <> 'postgres_hot'
                            OR p.location_ref IS DISTINCT FROM 'heimloc:' || r.id::text
                            OR p.ciphertext IS DISTINCT FROM r.ciphertext
                            OR p.nonce IS DISTINCT FROM r.nonce
                            OR p.key_ref IS DISTINCT FROM r.key_ref
                          )
                    ) <> 0
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'HAR-02 raw representation backfill is incomplete',
                    HINT = 'Repair the conflicting representation state and rerun alembic upgrade head; legacy raw bytes were not removed.';
            END IF;
        END
        $heimdal_raw_backfill_preflight$;
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_raw_representation_record_idx "
        "ON heimdal_raw_representation (record_id, sequence)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS heimdal_raw_representation_one_active_uq "
        "ON heimdal_raw_representation (record_id) WHERE active"
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
               AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_representation mutation is governed: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_raw_representation_no_mutation "
        "ON heimdal_raw_representation"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_raw_representation_no_mutation
        BEFORE UPDATE OR DELETE ON heimdal_raw_representation
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_representation_reject_mutation()
        """
    )

    # The encrypted bytes now have one durable owner. Keeping these columns
    # would create an undeclared second copy that retention could miss.
    op.execute("ALTER TABLE heimdal_raw_record DROP COLUMN ciphertext")
    op.execute("ALTER TABLE heimdal_raw_record DROP COLUMN nonce")
    op.execute("ALTER TABLE heimdal_raw_record DROP COLUMN key_ref")


def downgrade() -> None:
    raise RuntimeError(
        "HAR-02 raw-representation migration is forward-only: restoring one "
        "inline ciphertext column set cannot faithfully collapse multiple "
        "registered representations and would weaken all-copy deletion."
    )
