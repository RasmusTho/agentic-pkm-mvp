"""YSS-01 (#3916): YouTube Source Sync -- durable per-account source registry.

Slice YSS-01 of the YouTube Source Sync capability (parent #3915). Creates
`acquisition_source_registry`, the durable per-account-binding table backing
`app/knowledge_acquisition/source_registry.py`: one row per followed
collection (inbox/owned/liked/public playlist or subscription feed), per
account binding (`docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Source
registry`). Every later slice in this capability (YSS-02..11) reads or writes
through this table -- it is the one durable substrate for "which collections
does this account follow, with what policy, cursor, and state."

Two service-layer integrity rules are additionally backed by DB constraints
as defense-in-depth (the service layer, covering both the Postgres and
in-process memory backend identically, remains authoritative -- see the
module docstring in `source_registry.py`):

- unique `(collection_kind, collection_ref, account_binding_id)` binding
  triple. `account_binding_id` is nullable (RSS/public sources need none),
  and a plain `UNIQUE` constraint would treat two NULLs as distinct rows
  (standard SQL semantics) -- the index expression folds NULL to a fixed
  sentinel via `COALESCE` so the constraint holds even for account-less
  bindings.
- **exactly one enabled `inbox_playlist` per `account_binding_id`**, via a
  partial unique index on the same NULL-safe key, scoped to
  `collection_kind = 'inbox_playlist' AND enabled = true`. The service-layer
  swap (`SourceRegistry.set_inbox`) performs the disable-then-enable update
  as two statements in one transaction so the partial index is never
  transiently violated mid-swap.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM/ERE-02/ERE-04/ERE-05
precedent: schema-owning migrations in this repo have no downgrade path for
their tables. This table is a "new rebuildable-class table" per the issue's
SBS Impact (all sync state is rebuildable from the source + queue, INV-YSS
posture) -- rebuildable does not mean disposable-on-downgrade; it means an
operator-recovery story exists outside this migration, not that `downgrade()`
silently drops data.

Revision ID: bd79f3044759
Revises: e1d2c3b4a5f6
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "bd79f3044759"
down_revision: Union[str, None] = "e1d2c3b4a5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_NULL_ACCOUNT_SENTINEL = "__none__"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS acquisition_source_registry (
            binding_id TEXT PRIMARY KEY,
            account_binding_id TEXT,
            collection_kind TEXT NOT NULL,
            collection_ref TEXT NOT NULL,
            title TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT false,
            discovery_mode TEXT NOT NULL,
            poll_interval_seconds INTEGER NOT NULL,
            priority TEXT NOT NULL,
            cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_attempt_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            last_error JSONB,
            acquisition_policy JSONB NOT NULL,
            provenance JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT acquisition_source_registry_kind_chk CHECK (
                collection_kind IN (
                    'inbox_playlist', 'owned_playlist', 'liked_videos',
                    'public_playlist', 'subscription_feed'
                )
            ),
            CONSTRAINT acquisition_source_registry_discovery_mode_chk CHECK (
                discovery_mode IN ('api_poll', 'rss_poll', 'backfill_only')
            ),
            CONSTRAINT acquisition_source_registry_priority_chk CHECK (
                priority IN ('high', 'normal')
            ),
            CONSTRAINT acquisition_source_registry_poll_interval_chk CHECK (
                poll_interval_seconds >= 60 AND poll_interval_seconds <= 604800
            )
        )
        """
    )
    # Unique binding triple, NULL-safe on account_binding_id (see module docstring).
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_binding_triple_uq
        ON acquisition_source_registry (
            collection_kind,
            collection_ref,
            COALESCE(account_binding_id, '{_NULL_ACCOUNT_SENTINEL}')
        )
        """
    )
    # Exactly one enabled inbox_playlist per account binding (DB defense-in-depth;
    # the service layer performs the atomic swap so this is never violated
    # transiently -- see source_registry.py::SourceRegistry.set_inbox).
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_single_inbox_uq
        ON acquisition_source_registry (
            COALESCE(account_binding_id, '{_NULL_ACCOUNT_SENTINEL}')
        )
        WHERE collection_kind = 'inbox_playlist' AND enabled = true
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS acquisition_source_registry_account_idx "
        "ON acquisition_source_registry (account_binding_id)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-01 acquisition_source_registry migration is forward-only; this table is "
        "the durable per-account source registry for YouTube Source Sync (rebuildable "
        "from the source + queue per the capability's DRI posture, but not via "
        "migration downgrade), and is never dropped by downgrade."
    )
