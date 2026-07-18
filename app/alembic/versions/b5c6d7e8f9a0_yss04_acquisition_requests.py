"""YSS-04 (#3919): YouTube Source Sync -- durable acquisition request queue.

Slice YSS-04 of the YouTube Source Sync capability (parent #3915). Creates
`acquisition_requests`, the durable source-agnostic work-item table backing
`app/knowledge_acquisition/acquisition_requests.py`
(`docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest`):
discovery enqueues cheaply, a bounded drain acquires later, and restarts,
retries, and dedup converge on the row (INV-YSS-1..3). Deliberately a
migration-owned table, not outbox rows — the queue needs status queries,
trigger-append provenance, priority, and per-item backoff that append-only
events cannot carry.

Service-layer integrity rules backed by DB constraints as defense-in-depth
(the service layer, covering the Postgres and in-process memory backends
identically, remains authoritative — see the module docstring):

- `status` is one of `pending` / `in_progress` / `completed` / `dead_lettered`
  (retryable failures stay `pending` with a future `next_attempt_at`).
- `priority` is `high` | `normal` (drain order `(priority, requested_at)`:
  'high' < 'normal' sorts high-first on the plain column, so the drain index
  below serves the claim's status filter and its full ORDER BY).
- one request per `(source_kind, item_ref, policy_version)` — the identity
  triple behind the deterministic uuid5 `request_id` (INV-YSS-2), also
  enforced directly so a hand-written row cannot fork a parallel request.

Forward-only, following the KERNEL-04/KERNEL-05/HEIM/ERE-04 (`a1b2c3d4e5f6`)
/ YSS-01 / YSS-02 precedent: schema-owning migrations in this repo have no
downgrade path for their tables. This is a "new rebuildable-class table" per
the issue's SBS Impact — rebuildable means discovery re-enumerates and
converges through request idempotency, not that `downgrade()` silently drops
the queue.

Revision ID: b5c6d7e8f9a0
Revises: a2f1c3e4d5b6
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a2f1c3e4d5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

_TABLE = "acquisition_requests"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            request_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            item_ref TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'normal',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_failure JSONB,
            discovery_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
            policy_snapshot JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            policy_version INTEGER NOT NULL DEFAULT 1,
            trace_id TEXT,
            content_identity TEXT,
            artifact_path TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT acquisition_requests_status_chk CHECK (
                status IN ('pending', 'in_progress', 'completed', 'dead_lettered')
            ),
            CONSTRAINT acquisition_requests_priority_chk CHECK (
                priority IN ('high', 'normal')
            )
        )
        """
    )
    # Existing test/bootstrap-created tables predate the CHECK constraints; add
    # each migration-owned constraint idempotently so upgrading such a resource
    # reaches the same fail-loud schema as a fresh migration (YSS-01 precedent).
    for name, check in (
        (
            "acquisition_requests_status_chk",
            "status IN ('pending', 'in_progress', 'completed', 'dead_lettered')",
        ),
        ("acquisition_requests_priority_chk", "priority IN ('high', 'normal')"),
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
    # Drain path: the claim filters status='pending' and orders by
    # (priority ASC, requested_at ASC) — served by this index prefix; the
    # next_attempt_at due-gate is a residual filter on the matched rows.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS acquisition_requests_drain_idx "
        f"ON {_TABLE} (status, priority, requested_at)"
    )
    # Identity triple behind the deterministic request_id (INV-YSS-2), enforced
    # directly as defense-in-depth.
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS acquisition_requests_identity_uq "
        f"ON {_TABLE} (source_kind, item_ref, policy_version)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "YSS-04 acquisition_requests migration is forward-only; this table is the durable "
        "acquisition request queue for YouTube Source Sync (rebuildable by re-discovery "
        "converging through request idempotency, not via migration downgrade), and is never "
        "dropped by downgrade."
    )
