"""YSS-01 (#3916): acquisition source registry -- durable per-account source bindings.

First slice of the YouTube Source Sync capability (#3915, KAP Phase 4).
Creates the registry table backing
`app/knowledge_acquisition/source_registry.py`: one durable row per followed
collection, per account binding, carrying policy, cursor, and degradation
state (`docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Source registry`).

Integrity rules expressible in the database are enforced here (defense in
depth on top of the service layer, which enforces the same rules identically
for the in-memory test backend):

- unique binding triple `(collection_kind, collection_ref,
  account_binding_id)` -- as two partial unique indexes because
  `account_binding_id` is nullable (RSS/public sources need no account);
- exactly one **enabled** `inbox_playlist` per `account_binding_id`
  (partial unique index; "change inbox" is an atomic swap in the service);
- `poll_interval_seconds` bounds `[60, 604800]`;
- Watch Later (`WL`) / Watch History (`HL`) refused (`CHECK collection_ref
  NOT IN ('WL','HL')`) -- the official Data API does not expose them and the
  capability never uses cookies/scraping (owner decision record 2026-07-16).

Forward-only, following the KERNEL-04/KERNEL-05/HEIM precedent: schema-
owning migrations in this repo have no downgrade path for their tables.

Revision ID: a7f3c2e9d1b4
Revises: e1d2c3b4a5f6
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a7f3c2e9d1b4"
down_revision: Union[str, None] = "e1d2c3b4a5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS acquisition_source_registry (
            binding_id uuid PRIMARY KEY,
            account_binding_id uuid,
            collection_kind text NOT NULL CHECK (collection_kind IN (
                'inbox_playlist', 'owned_playlist', 'liked_videos',
                'public_playlist', 'subscription_feed')),
            collection_ref text NOT NULL CHECK (collection_ref NOT IN ('WL', 'HL')),
            title text NOT NULL DEFAULT '',
            enabled boolean NOT NULL DEFAULT true,
            discovery_mode text NOT NULL CHECK (discovery_mode IN (
                'api_poll', 'rss_poll', 'backfill_only')),
            poll_interval_seconds integer CHECK (
                poll_interval_seconds IS NULL
                OR (poll_interval_seconds >= 60 AND poll_interval_seconds <= 604800)),
            priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('high', 'normal')),
            cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_attempt_at timestamptz,
            last_success_at timestamptz,
            last_error jsonb,
            acquisition_policy jsonb NOT NULL,
            provenance jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_triple_uq
            ON acquisition_source_registry (collection_kind, collection_ref, account_binding_id)
            WHERE account_binding_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_triple_noacct_uq
            ON acquisition_source_registry (collection_kind, collection_ref)
            WHERE account_binding_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_single_inbox_uq
            ON acquisition_source_registry (account_binding_id)
            WHERE collection_kind = 'inbox_playlist' AND enabled AND account_binding_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS acquisition_source_registry_account_idx
            ON acquisition_source_registry (account_binding_id)
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-01 source-registry migration is forward-only; registry rows carry "
        "durable cursors and policy state and are never dropped by downgrade."
    )
