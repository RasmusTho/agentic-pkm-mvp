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
- `stream_watermark:<stream_id>` -- the max observed instant consumed per
  stream (the observed-time frontier quiescence closure is measured against).

Never authoritative: this table is pure tick-runtime bookkeeping, fully
replayable from the underlying streams (Heimdal observation log; DB outbox).

Recovery posture (deliberate, asymmetric with `heimdal_observation_cursor`):
this table CO-LOCATES the vault-activity cursor with open-segment state while
the Heimdal cursor lives in its own table, so wiping `episode_engine_state`
alone resets ONE stream to event zero while the Heimdal cursor stays advanced
-- a skewed single-stream replay, NOT a symmetric rebuild, and not a
supported operator action. Operator recovery = reset BOTH cursor families
together (delete this table's rows AND the `mimer.episode_resolution_engine`
row in `heimdal_observation_cursor`): the full both-stream replay from event
zero is deterministic and cannot double-propose, because segments fold by key
and every closed segment mints a deterministic episode_id whose
already-written note is skipped at emission
(`app/episodes/segmenter.py::_deterministic_episode_id` / `_emit_proposal`;
asserted by
`tests/episodes/test_segmentation_core.py::test_emission_idempotent_under_redelivery`).

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
