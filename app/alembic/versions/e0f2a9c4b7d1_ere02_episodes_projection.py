"""ERE-02 (#3177): Episode note store rebuildable ``episodes`` projection.

Slice ERE-02 of the Episode Resolution Engine (parent #3175, ADR-0051 OD-1/OD-2). Creates
the ``episodes`` table backing ``app/jobs/episodes_projection.py``:

- Episode notes (``app/episodes/store.py``, one markdown note per episode under
  ``episodes/`` in the vault) are vault-canonical (SoR). This table is a rebuildable query
  projection over them only -- never authoritative, and never written except by
  ``rebuild_episodes_projection()``.
- ``episode_id`` is the fused id (``ep-<uuid>``), a disjoint identifier space from Heimdal's
  per-capture-session ``episode_id`` (``app/episodes/ids.py``).

Forward-only, following the KERNEL-04/KERNEL-05/HEIM (``8b21e6a1f0c4``) precedent:
schema-owning migrations in this repo have no downgrade path for their tables. Losing this
projection loses only query speed -- the projection rebuilds row-for-row from the vault.

Revision ID: e0f2a9c4b7d1
Revises: b1c2d3e4f5a6
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "e0f2a9c4b7d1"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            title TEXT NOT NULL,
            time_start TIMESTAMPTZ NOT NULL,
            time_end TIMESTAMPTZ,
            closed BOOLEAN NOT NULL DEFAULT false,
            segmentation TEXT NOT NULL,
            parent_episode TEXT,
            space JSONB NOT NULL DEFAULT '[]'::jsonb,
            protagonists JSONB NOT NULL DEFAULT '[]'::jsonb,
            goal JSONB NOT NULL DEFAULT '[]'::jsonb,
            causation JSONB NOT NULL DEFAULT '[]'::jsonb,
            derived_from JSONB NOT NULL DEFAULT '[]'::jsonb,
            note_path TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT episodes_id_shape_chk CHECK (episode_id ~ '^ep-[0-9a-fA-F-]{36}$'),
            CONSTRAINT episodes_segmentation_chk
                CHECK (segmentation IN ('proposed', 'accepted', 're-cut'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodes_scope_idx ON episodes (scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodes_time_start_idx ON episodes (time_start)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodes_closed_idx ON episodes (closed)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodes_parent_episode_idx ON episodes (parent_episode)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "episodes projection migration is forward-only; the projection rebuilds from the "
        "vault-canonical Episode notes (SoR) and is never dropped by downgrade."
    )
