"""CDLM-07 (#4387): Meeting block-ownership registry v0 — the INV-CDLM-6 boundary.

Creates the tables backing `app/heimdal/meeting_blocks.py`:

- `heimdal_meeting_block`: one row per meeting-page block —
  `{block_id, owner, block_type, provenance, content, position, revision}`.
  Mutations happen only through the shared ownership guard
  (`apply_block_write`); at the DB level the guard trigger below enforces the
  invariants no application bug may cross: identity fields (block_id,
  session_id, owner, block_type, created_at) are immutable, rows are never
  deleted, and a `user_note` row's content/position may only change together
  with a provenance that *claims* the user-editor kind. The trigger checks
  that claim, not authority — a bypassing writer that also forges the
  provenance kind passes it; real authorization lives in the application
  guard, and this trigger is the backstop against honest-but-buggy writers.
- `heimdal_meeting_user_note_revision`: append-only edit history, one row per
  `(note_block_id, revision)` — the durable acknowledgement rows for the
  user-note endpoint (CDLM-01 ack-ordering family). User notes are Human
  Knowledge Artifacts; their history is never rewritten.
- `heimdal_meeting_block_refusal`: append-only record of fail-closed refusals
  (who attempted, what target, why) surfaced as needs-attention.

Forward-only: dropping the registry would destroy the only durable record of
which blocks are human-authored, which is the loss class this slice exists to
make impossible.

Revision ID: c9e4a1b6d3f5
Revises: b8d3f0a5c2e4
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "c9e4a1b6d3f5"
down_revision: Union[str, None] = "b8d3f0a5c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_block (
            block_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            owner TEXT NOT NULL,
            block_type TEXT NOT NULL,
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            content TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,
            retired BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revised_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_meeting_block_session_idx "
        "ON heimdal_meeting_block (session_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_block_guard_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'heimdal_meeting_block rows are never deleted (CDLM-07)';
            END IF;
            IF NEW.block_id IS DISTINCT FROM OLD.block_id
               OR NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.owner IS DISTINCT FROM OLD.owner
               OR NEW.block_type IS DISTINCT FROM OLD.block_type
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'heimdal_meeting_block identity fields are immutable (CDLM-07)';
            END IF;
            IF OLD.block_type = 'user_note'
               AND (NEW.content IS DISTINCT FROM OLD.content
                    OR NEW.position IS DISTINCT FROM OLD.position)
               AND COALESCE(NEW.provenance->>'kind', '') <> 'user_editor' THEN
                RAISE EXCEPTION 'heimdal_meeting_block: user_note content is writable only under user_editor provenance (INV-CDLM-6)';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_block_guard ON heimdal_meeting_block"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_block_guard
        BEFORE UPDATE OR DELETE ON heimdal_meeting_block
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_block_guard_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_user_note_revision (
            note_block_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            text TEXT NOT NULL,
            editor_identity TEXT NOT NULL,
            written_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (note_block_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_user_note_revision_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_meeting_user_note_revision is append-only (CDLM-07): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_user_note_revision_no_update "
        "ON heimdal_meeting_user_note_revision"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_user_note_revision_no_update
        BEFORE UPDATE OR DELETE ON heimdal_meeting_user_note_revision
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_user_note_revision_reject_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS heimdal_meeting_block_refusal (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            block_id TEXT NOT NULL,
            attempted_by JSONB NOT NULL DEFAULT '{}'::jsonb,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS heimdal_meeting_block_refusal_session_idx "
        "ON heimdal_meeting_block_refusal (session_id)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_meeting_block_refusal_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_meeting_block_refusal is append-only (CDLM-07): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS heimdal_meeting_block_refusal_no_update "
        "ON heimdal_meeting_block_refusal"
    )
    op.execute(
        """
        CREATE TRIGGER heimdal_meeting_block_refusal_no_update
        BEFORE UPDATE OR DELETE ON heimdal_meeting_block_refusal
        FOR EACH ROW EXECUTE FUNCTION heimdal_meeting_block_refusal_reject_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "CDLM-07 meeting-block migration is forward-only; the block registry is the "
        "durable record of human vs derived ownership (INV-CDLM-6) and is never "
        "dropped by downgrade."
    )
