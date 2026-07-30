"""EROJ-01 (#4350): entity-review operation journal — committed visibility fence.

Creates `entity_review_operations`, backing
`app/heimdal/entity_review_operation_journal.py`: one row per deterministic
entity-review merge operation (INV-EROJ-2 — the active vault identity, queue
entry id, decision-list position, SHA-256 digest of the exact human-authored
decision mapping, and the original `{from_id, into_id}` derive the id). The
row commits BEFORE the first register note effect; its terminal
`event_committed` state commits atomically with the operation's
deterministically keyed `heimdal.register.entity.merged` outbox row; and a
merge queue entry may leave `entities/review.md` `pending` only after a fresh
connection observes both committed rows (INV-EROJ-3 — the #4253 stop-loss
failure this table exists to close).

The partial unique index enforces one *active* (non-cleared) operation per
`(vault_identity, queue_entry_id)`: a changed decision mapping derives a
different operation_id and its INSERT fails closed at the database
(INV-EROJ-2/6) instead of minting a colliding second operation. `cleared`
rows fall out of the index so a later re-queue of the same queue entry id can
claim a fresh operation.

Operational coordination evidence only (INV-EROJ-1): entity notes remain
canonical identity truth and `entities/review.md` remains the human decision
history; this table never decides that two entities are the same.

Forward-only per the repo precedent: dropping this table would erase the only
durable retry anchors for in-flight merge operations (an applied register
effect whose event recovery depends on its committed operation row).

The DDL below is byte-identical with the module's test-only autocreate shape;
parity is asserted by
tests/migrations/test_entity_review_operation_journal_schema_parity.py.

Revision ID: e7a2b9c4d1f8
Revises: d0f5b2c7e4a6
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "e7a2b9c4d1f8"
down_revision: Union[str, None] = "d0f5b2c7e4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS entity_review_operations (
    operation_id UUID PRIMARY KEY,
    vault_identity TEXT NOT NULL,
    queue_entry_id TEXT NOT NULL,
    decision_position INTEGER NOT NULL,
    decision_digest TEXT NOT NULL,
    from_id TEXT NOT NULL,
    into_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'claimed'
        CONSTRAINT entity_review_operations_state_chk
        CHECK (state IN ('claimed', 'event_committed', 'cleared')),
    outbox_event_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
    )
    op.execute(
        """
CREATE UNIQUE INDEX IF NOT EXISTS entity_review_operations_active_entry_idx
    ON entity_review_operations (vault_identity, queue_entry_id)
    WHERE state <> 'cleared'
"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "EROJ-01 entity-review operation journal migration is forward-only; the "
        "journal rows are the durable retry anchors for in-flight merge operations "
        "(INV-EROJ-3) and are never dropped by downgrade."
    )
