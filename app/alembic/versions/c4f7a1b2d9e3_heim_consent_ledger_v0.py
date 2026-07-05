"""HEIM (#3042): Consent ledger v0 -- grants table + self_record seed.

Slice A5 of Epic #3019 (Heimdal v1). Creates the append-only consent-grant
ledger backing `app/heimdal/consent_ledger.py`:

- `heimdal_consent_grant`: append-only ledger of consent grants and
  revocations (FABLE_COMPANION §6.1). A grant row is never updated or
  deleted; a revocation is a NEW row (`basis='revocation'`,
  `revokes_grant_ref` naming the grant it lapses) -- same HEIM-1 discipline
  as the observation log (migration `8b21e6a1f0c4`), enforced here with the
  identical trigger pattern (defense in depth on top of the Python store
  exposing no update/delete API).
- Seeds the standing `self_record` grant (v1 posture A, FABLE_COMPANION
  §6.1 basis 1): "the act of deliberately recording is the grant", modeled
  as one standing ledger entry per capture adapter rather than per-memo
  ceremony.
- B-shaped fields present-but-dormant (ADR-0049 §3 / FABLE_COMPANION §6.1
  grant-record shape): `vad_gate`, `third_party_policy`, `retention`,
  `erasure` columns exist now, populated with v1-inert defaults, so
  enabling Posture B later is a grant + adapter change, not a schema
  redesign.

This does not touch `heimdal_observation_log` / `heimdal_observation_cursor`
(migration `8b21e6a1f0c4`) -- the ledger is its own append-only table;
grant/revocation events are ALSO published onto the existing observation
log by `app/heimdal/consent_ledger.py` (event topics owned by sibling
slice A4, referenced by value here, not redefined).

Forward-only, following the KERNEL-04/KERNEL-05/HEIM-1 precedent:
schema-owning migrations in this repo have no downgrade path for their
tables.

Revision ID: c4f7a1b2d9e3
Revises: 8b21e6a1f0c4
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "c4f7a1b2d9e3"
down_revision: Union[str, None] = "8b21e6a1f0c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_SELF_RECORD_GRANT_REF = "grant-self-record-v1"
_SELF_RECORD_SCOPE = "device+adapter:v1-voice-memo"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_consent_grant (
            id UUID PRIMARY KEY,
            grant_ref TEXT NOT NULL,
            basis TEXT NOT NULL,
            scope TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            granted_at TIMESTAMPTZ NOT NULL,
            expiry TIMESTAMPTZ,
            capture_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
            third_party_policy TEXT NOT NULL DEFAULT 'degrade',
            vad_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
            third_party JSONB NOT NULL DEFAULT '{}'::jsonb,
            retention JSONB NOT NULL DEFAULT '{}'::jsonb,
            erasure JSONB NOT NULL DEFAULT '{}'::jsonb,
            revokes_grant_ref TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sequence BIGSERIAL NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_consent_grant_seq_idx "
        "ON heimdal_consent_grant (sequence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_consent_grant_grant_ref_idx "
        "ON heimdal_consent_grant (grant_ref)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_consent_grant_scope_idx "
        "ON heimdal_consent_grant (scope)"
    )

    # HEIM-1: append-only truth, enforced at the database level (defense in
    # depth on top of the Python store never exposing update/delete) --
    # identical pattern to heimdal_observation_log (migration 8b21e6a1f0c4).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_consent_grant_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_consent_grant is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_consent_grant_no_update ON heimdal_consent_grant"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_consent_grant_no_update
        BEFORE UPDATE OR DELETE ON heimdal_consent_grant
        FOR EACH ROW EXECUTE FUNCTION heimdal_consent_grant_reject_mutation()
        """
    )

    # Seed the standing self_record grant (v1 posture A). Idempotent: reruns
    # (e.g. a bootstrap re-apply) must not duplicate the standing grant.
    op.execute(
        f"""
        INSERT INTO heimdal_consent_grant (
            id, grant_ref, basis, scope, granted_by, granted_at,
            expiry, capture_profile, third_party_policy,
            vad_gate, third_party, retention, erasure, revokes_grant_ref, payload
        )
        SELECT
            gen_random_uuid(),
            '{_SELF_RECORD_GRANT_REF}',
            'self_record',
            '{_SELF_RECORD_SCOPE}',
            'operator',
            now(),
            NULL,
            '{{"modalities": ["speech"], "degradation_rules": ["third_party_speech"]}}'::jsonb,
            'degrade',
            '{{"enabled": false}}'::jsonb,
            '{{"policy": "degrade"}}'::jsonb,
            '{{"hard_retention_days": null}}'::jsonb,
            '{{"supported": false}}'::jsonb,
            NULL,
            '{{"note": "standing self_record grant seeded by migration c4f7a1b2d9e3, FABLE_COMPANION §6.1 basis 1"}}'::jsonb
        WHERE NOT EXISTS (
            SELECT 1 FROM heimdal_consent_grant WHERE grant_ref = '{_SELF_RECORD_GRANT_REF}'
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM consent-ledger migration is forward-only; the ledger is the "
        "authoritative capture-gate record and is never dropped by downgrade."
    )
