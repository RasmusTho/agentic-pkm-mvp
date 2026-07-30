"""ERE-04 (#3179): Two-stream segmentation core -- engine tick-runtime state.

Slice ERE-04 of the Episode Resolution Engine (parent #3175). Creates
`episode_engine_state`, a small generic key/value table backing
`app/episodes/engine_state.py`, holding the row families the segmentation
tick needs across restarts (spec Restart/Durability Posture: "cursors are
durable DB rows; a restart resumes from cursors and re-derives open
segments"):

- `cursor:vault.activity:<consumer_id>` -- the segmenter's own durable read
  position over the DB `outbox` table's vault-activity topics
  (`ingest.vault.changed` / `ingest.object.created` / `ingest.object.deleted`).
  This is a NEW per-consumer cursor primitive over the shared `outbox` table,
  independent of that table's single `delivered_at` flag (the worker
  dispatcher's own shared delivery marker, docs/EVENTS.md :: Outbox consumer
  contract) -- a second logical consumer marking or filtering on
  `delivered_at` would race the worker's own dispatch. `heimdal.observations`
  reuses the EXISTING `heimdal_observation_cursor` table via
  `app.heimdal.publish` and needs no new row family here.
- `open_segment:<scope>` -- the accumulated situation-model state of one
  scope's currently-open (not yet proposed) segment, so a restart re-derives
  in-flight segmentation instead of losing it.

Quiescence-closure frontiers are computed per-scope from each tick's own
consumed signals (not carried across ticks), so there is no durable
`stream_watermark` row family in this table.

The vault-activity cursor and open-segment row families are pure tick-runtime
bookkeeping, replayable from their underlying streams. Later calendar work
also uses this generic table for `calendar_consumed_signal:` rows: those are a
durable idempotency boundary after a segment closes, not resettable cursor
state.

Recovery posture (deliberate, asymmetric with `heimdal_observation_cursor`):
ordinary recovery MUST preserve `calendar_consumed_signal:` rows. There is no
supported blanket `episode_engine_state` reset or paired cursor reset while
that ledger exists, because the fixed calendar window cannot reconstruct all
past closed identities and clearing it can replay stale evidence into a later
segment. A future full historical calendar rebuild may define an explicit
replacement procedure; until then, do not delete this table's rows.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM (`8b21e6a1f0c4`)/ERE-02
(`e0f2a9c4b7d1`) precedent: schema-owning migrations in this repo have no
downgrade path for their tables.

Revision ID: a1b2c3d4e5f6
Revises: e0f2a9c4b7d1
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e0f2a9c4b7d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS episode_engine_state (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "ERE-04 segmentation engine-state migration is forward-only; this table is "
        "rebuildable tick-runtime bookkeeping (cursors + open-segment state) and is "
        "never dropped by downgrade."
    )
