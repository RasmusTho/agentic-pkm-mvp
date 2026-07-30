"""CDLM-02 (#4385): Meeting session/segment ledger v0 -- gaps become legible.

Creates the tables backing `app/heimdal/meeting_ledger.py`, the durable answer
to "which parts of this meeting does the hub durably hold?" (INV-CDLM-9):

- `heimdal_meeting_session`: one row per client-minted `session_id`. Open is an
  insert (`ON CONFLICT DO NOTHING` -- a re-post replays the recorded outcome);
  close sets `closed`/`final_seq_count`/`closed_at` exactly once (`WHERE closed
  = false`), and sessions never re-open, so the guarded-update trigger below
  rejects any UPDATE that would flip `closed` back or change identity fields.
- `heimdal_meeting_segment`: exactly one row per `(session_id, session_seq)`
  (the primary key -- INV-CDLM-3's idempotent-row rule at the schema level),
  referencing the CDLM-01 admission receipt. Append-only: a different content
  hash for an existing pair never replaces the row (fail closed).
- `heimdal_meeting_segment_conflict`: the recorded fail-closed conflicts,
  surfaced as `needs_attention` in the gap report. Append-only.

No person attribution anywhere (INV-CDLM-8). Forward-only, per the
KERNEL-04/KERNEL-05/HEIM-1 precedent: dropping these tables would destroy the
only durable record of meeting completeness, which CDLM-03/06/08/09 gate on.

Revision ID: a7c2e9f4b1d3
Revises: e3c1a7f5d2b8
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a7c2e9f4b1d3"
down_revision: Union[str, None] = "e3c1a7f5d2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_session (
            session_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            template_selection JSONB NOT NULL DEFAULT '{}'::jsonb,
            opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed BOOLEAN NOT NULL DEFAULT false,
            final_seq_count INTEGER,
            closed_at TIMESTAMPTZ,
            trace_id TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # Sessions never re-open and never change identity: the only permitted
    # mutation is the one-time open -> closed transition.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_session_guard_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'heimdal_meeting_session rows are never deleted';
            END IF;
            IF OLD.closed AND NOT NEW.closed THEN
                RAISE EXCEPTION 'heimdal_meeting_session: sessions never re-open (CDLM-02)';
            END IF;
            IF OLD.closed THEN
                RAISE EXCEPTION 'heimdal_meeting_session: a closed session is immutable (CDLM-02)';
            END IF;
            IF NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.device_id IS DISTINCT FROM OLD.device_id
               OR NEW.template_selection IS DISTINCT FROM OLD.template_selection
               OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
                RAISE EXCEPTION 'heimdal_meeting_session: identity fields are immutable (CDLM-02)';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_session_guard ON heimdal_meeting_session"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_session_guard
        BEFORE UPDATE OR DELETE ON heimdal_meeting_session
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_session_guard_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_segment (
            session_id TEXT NOT NULL,
            session_seq INTEGER NOT NULL,
            receipt_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            raw_ref TEXT NOT NULL DEFAULT '',
            admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            late BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (session_id, session_seq)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_meeting_segment_session_idx "
        "ON heimdal_meeting_segment (session_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_segment_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_meeting_segment is append-only (fail closed, CDLM-02): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_segment_no_update ON heimdal_meeting_segment"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_segment_no_update
        BEFORE UPDATE OR DELETE ON heimdal_meeting_segment
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_segment_reject_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_segment_conflict (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            session_seq INTEGER NOT NULL,
            attempted_content_sha256 TEXT NOT NULL,
            attempted_receipt_id TEXT NOT NULL DEFAULT '',
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_meeting_segment_conflict_session_idx "
        "ON heimdal_meeting_segment_conflict (session_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_segment_conflict_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_meeting_segment_conflict is append-only (CDLM-02): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_segment_conflict_no_update "
        "ON heimdal_meeting_segment_conflict"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_segment_conflict_no_update
        BEFORE UPDATE OR DELETE ON heimdal_meeting_segment_conflict
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_segment_conflict_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "CDLM-02 meeting-ledger migration is forward-only; the ledger is the durable "
        "definition of meeting completeness (INV-CDLM-9) and is never dropped by "
        "downgrade."
    )
