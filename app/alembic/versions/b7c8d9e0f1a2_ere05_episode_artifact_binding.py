"""ERE-05 (#3180): episode-ref assignment -- artifact binding ledger.

Slice ERE-05 of the Episode Resolution Engine (parent #3175). Creates
`episode_artifact_binding`, the DB-side "bundle row" ledger backing
`app/episodes/assignment.py`: one row per (artifact_ref, episode_id) pair
recording that an in-bounds artifact's `episode_ref` was upgraded from
`unbound` to a real episode id (spec: "upgrade in-bounds artifacts' bundles
from `episode_ref='unbound'` to `pending [ep-...]`",
docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md).

- `artifact_ref` reuses the SAME provenance-ref shape segmentation signals
  already carry (`heimdal.observations:<observation_id>` /
  `vault.activity:<outbox_row_id>`, see `app/episodes/segmenter.py`), so a
  binding always resolves back to the exact signal that earned it.
- `basis` ('provenance' | 'time_overlap') + `confidence` are the HEIM-6-honest
  confidence floor (issue Scope): a `derived_from`-anchored artifact is
  binding-strength (`provenance`, confidence 1.0); a bounds-only match is
  proposed-only (`time_overlap`, confidence 0.5) -- never a confident claim
  from a weak correlation.
- `binding_state` ('active' | 'corrected') plus `corrected_at` carries
  un-assignment/correction on re-cut (spec point 5): a binding a later tick
  no longer supports is corrected (not deleted), so history stays
  inspectable -- "corrections are ordinary bundle updates with provenance,
  never silent."
- PRIMARY KEY (artifact_ref, episode_id) is the idempotency mechanism per
  (artifact, episode): re-ticking the same pair is an upsert, never a
  duplicate row.

Rebuildable/never-authoritative posture: this ledger is the DB-side
projection of a derived fact (which in-bounds artifacts bind to which
episodes); the episode notes themselves (`app/episodes/store.py`, ADR-0051
OD-1/OD-2) remain the vault-canonical record. `episode_ref` on the artifact's
own bundle is `pending` (not authority) until an ERE-07 acceptance/re-cut
transition -- this table never emits or requires an AuthorityReceipt.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM/ERE-02/ERE-04
precedent: schema-owning migrations in this repo have no downgrade path for
their tables.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS episode_artifact_binding (
            artifact_ref TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            basis TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            binding_state TEXT NOT NULL DEFAULT 'active',
            rule TEXT NOT NULL,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            corrected_at TIMESTAMPTZ,
            PRIMARY KEY (artifact_ref, episode_id),
            CONSTRAINT episode_artifact_binding_basis_chk
                CHECK (basis IN ('provenance', 'time_overlap')),
            CONSTRAINT episode_artifact_binding_state_chk
                CHECK (binding_state IN ('active', 'corrected'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episode_artifact_binding_episode_idx "
        "ON episode_artifact_binding (episode_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episode_artifact_binding_scope_idx "
        "ON episode_artifact_binding (scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episode_artifact_binding_state_idx "
        "ON episode_artifact_binding (binding_state)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "ERE-05 episode-artifact-binding migration is forward-only; this ledger is a "
        "rebuildable DB-side projection of the assignment rule over vault-canonical "
        "episode notes + segmentation signals, and is never dropped by downgrade."
    )
