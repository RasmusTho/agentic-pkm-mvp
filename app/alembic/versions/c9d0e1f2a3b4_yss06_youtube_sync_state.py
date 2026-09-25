"""YSS-06 (#3921): YouTube Source Sync -- scheduler state and single-runner lease.

Slice YSS-06 of the YouTube Source Sync capability (parent #3915). Creates
`youtube_sync_state`, the small generic key/value table backing
`app/knowledge_acquisition/sync_state.py`
(`docs/YOUTUBE_SOURCE_SYNC/SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md`): the
single-run lease (INV-YSS-6), per-source failure backoff, and the tick
heartbeat plus counters that YSS-09 projects.

Follows the ERE-04 (`a1b2c3d4e5f6`) `episode_engine_state` precedent rather
than inventing a second state-table shape: one generic key, a JSON value, and
no per-family columns. The families are documented in the service module, which
remains authoritative; this table deliberately holds no schema opinion about
them, because they are tick-runtime bookkeeping whose shape will move with
YSS-09.

Every row here is rebuildable. The lease is transient by construction, backoff
re-derives from the next poll outcome, and the heartbeat is an observation of
the last tick rather than a source of truth about anything. Losing this table
costs one duplicate poll interval, never an item: item identity lives in
`acquisition_requests` and cursors live in the source registry.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM/ERE-04 / YSS-01 / YSS-02 /
YSS-04 precedent: schema-owning migrations in this repo have no downgrade path
for their tables.

Revision ID: c9d0e1f2a3b4
Revises: b7e3c9d5a1f2
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b7e3c9d5a1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_TABLE = "youtube_sync_state"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # The lease take-over predicate filters on the expiry inside `value`, and
    # the heartbeat projection reads the newest rows; both are cheap here only
    # because this table stays tiny, but the index keeps that true if a future
    # slice adds one row family per source.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_updated_at ON {_TABLE} (updated_at DESC)"
    )


def downgrade() -> None:
    raise RuntimeError(
        f"{_TABLE} is forward-only: dropping it would discard the live "
        "single-runner lease while a runner may still believe it holds one"
    )
