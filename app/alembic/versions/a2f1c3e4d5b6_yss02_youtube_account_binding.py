"""YSS-02 (#3917): YouTube Source Sync -- durable, non-secret account binding.

Slice YSS-02 of the YouTube Source Sync capability (parent #3915). Creates
`youtube_account_binding`, the durable non-secret table backing
`app/knowledge_acquisition/youtube_account_binding.py`: one row per connected
YouTube/Google account -- the `account_binding_id` that authenticated rows in
`acquisition_source_registry` (YSS-01) reference. It records the provider
channel id (`UC...` -- identity, never a title), a display label, the
connected/degraded auth state + reason code, the granted scopes, and
timestamps. It carries **no secret**: tokens live in the AES-256-GCM
`youtube_token_store` file, client credentials live in host env
(`docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and private
bindings`, INV-YSS-5).

Two service-layer integrity rules are backed by DB constraints as
defense-in-depth (the service layer, covering both Postgres and the in-process
memory backend identically, remains authoritative -- see the module docstring
in `youtube_account_binding.py`):

- `state` is one of `connected` / `degraded`.
- a `connected` binding carries no `reason_code` (a degraded reason and a
  healthy state are mutually exclusive).

plus a unique `(provider, provider_channel_id)` index: one binding per account.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM/YSS-01 precedent:
schema-owning migrations in this repo have no downgrade path for their tables.
This is a "new rebuildable-class table" per the issue's SBS Impact (all sync
state is rebuildable from the source + queue) -- rebuildable means an
operator-recovery story exists outside this migration, not that `downgrade()`
silently drops the account bindings.

Revision ID: a2f1c3e4d5b6
Revises: bd79f3044759
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a2f1c3e4d5b6"
down_revision: Union[str, None] = "bd79f3044759"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_TABLE = "youtube_account_binding"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            account_binding_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_channel_id TEXT NOT NULL,
            display_label TEXT NOT NULL,
            state TEXT NOT NULL,
            reason_code TEXT,
            scopes JSONB NOT NULL,
            obtained_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT youtube_account_binding_state_chk CHECK (
                state IN ('connected', 'degraded')
            ),
            CONSTRAINT youtube_account_binding_connected_reason_chk CHECK (
                state <> 'connected' OR reason_code IS NULL
            )
        )
        """
    )
    # Existing test/bootstrap-created tables predate the CHECK constraints; add
    # each migration-owned constraint idempotently so upgrading such a resource
    # reaches the same fail-loud schema as a fresh migration (YSS-01 precedent).
    for name, check in (
        ("youtube_account_binding_state_chk", "state IN ('connected', 'degraded')"),
        ("youtube_account_binding_connected_reason_chk", "state <> 'connected' OR reason_code IS NULL"),
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = '{name}'
                      AND conrelid = '{_TABLE}'::regclass
                ) THEN
                    ALTER TABLE {_TABLE} ADD CONSTRAINT {name} CHECK ({check});
                END IF;
            END $$;
            """
        )
    # One binding per account (INV-YSS-9: identity is the channel id, never a title).
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS youtube_account_binding_channel_uq
        ON {_TABLE} (provider, provider_channel_id)
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-02 youtube_account_binding migration is forward-only; this table is the durable "
        "per-account OAuth binding registry for YouTube Source Sync (rebuildable by re-consenting, "
        "not via migration downgrade), and is never dropped by downgrade."
    )
