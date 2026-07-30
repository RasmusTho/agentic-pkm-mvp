"""CDLM-06 (#4386): Meeting transcript/analysis projection state v0.

Creates the tables backing `app/heimdal/meeting_projection.py`:

- `heimdal_meeting_asr_derivation`: one row per admitted segment *content
  hash* — the durable "each segment derives exactly once" record (INV-CDLM-3).
  `status` is `ok` or `failed`; a failed row is legible needs-attention state
  and is the only row the retry path may replace (DELETE guarded on
  `status = 'failed'` in the store), so the mutation guard below rejects
  UPDATE always and DELETE only for `ok` rows.
- `heimdal_meeting_analysis_revision`: one row per `(session_id, revision)` —
  the generic-default-template analysis blocks with
  `{revision, derived_from, template_id, engine}` provenance, cached by
  input-set identity so an identical admitted set never mints a new revision.
  Prior revisions stay addressable up to a config-capped retention bound, so
  DELETE is permitted (the store prunes rows older than the retention window);
  UPDATE is rejected — a revision is immutable once derived (INV-CDLM-5's
  honesty: derived text never silently rewrites; change arrives as a new
  revision).

Projection state is derived and rebuildable from admitted segments; it is
never semantic authority. Forward-only per the repo's schema-owning migration
precedent — dropping these tables silently would discard the only durable
record of which content hashes have already derived, and every replayed
segment would re-derive (double-count) on the next admission.

Revision ID: b8d3f0a5c2e4
Revises: a7c2e9f4b1d3
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "b8d3f0a5c2e4"
down_revision: Union[str, None] = "a7c2e9f4b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_asr_derivation (
            content_sha256 TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            segments JSONB NOT NULL DEFAULT '[]'::jsonb,
            language TEXT NOT NULL DEFAULT 'unknown',
            error TEXT NOT NULL DEFAULT '',
            engine JSONB NOT NULL DEFAULT '{}'::jsonb,
            derived_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_asr_derivation_guard_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'heimdal_meeting_asr_derivation rows are immutable (CDLM-06): derive once per content hash';
            END IF;
            IF OLD.status <> 'failed' THEN
                RAISE EXCEPTION 'heimdal_meeting_asr_derivation: only failed derivations may be replaced (CDLM-06)';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_asr_derivation_guard "
        "ON heimdal_meeting_asr_derivation"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_asr_derivation_guard
        BEFORE UPDATE OR DELETE ON heimdal_meeting_asr_derivation
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_asr_derivation_guard_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_analysis_revision (
            session_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            input_set_sha256 TEXT NOT NULL,
            derived_from JSONB NOT NULL,
            template_id TEXT NOT NULL,
            blocks JSONB NOT NULL,
            engine JSONB NOT NULL DEFAULT '{}'::jsonb,
            derived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, revision)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_meeting_analysis_revision_set_idx "
        "ON heimdal_meeting_analysis_revision (session_id, input_set_sha256)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_analysis_revision_guard_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'heimdal_meeting_analysis_revision rows are immutable (CDLM-06): change arrives as a new revision';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_analysis_revision_guard "
        "ON heimdal_meeting_analysis_revision"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_analysis_revision_guard
        BEFORE UPDATE ON heimdal_meeting_analysis_revision
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_analysis_revision_guard_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "CDLM-06 meeting-projection migration is forward-only; the derivation table is "
        "the durable derive-once record (INV-CDLM-3) and is never dropped by downgrade."
    )
