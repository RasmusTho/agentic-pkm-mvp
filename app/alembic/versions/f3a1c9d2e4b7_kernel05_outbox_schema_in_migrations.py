"""KERNEL-05 (#2850): outbox schema moves into Alembic.

Follow-up to KERNEL-04 (#2766, PR #2849), which moved the `store_*` /
`vector_index_meta` DDL into Alembic. RESEARCH-02 (#2780) identified the same
create-on-boot class in the outbox path: `app/services/outbox.py::bootstrap()`
runs the DB outbox DDL imperatively (including a nested
`except Exception: pass` around `ensure_schema` — a silent-failure seam on the
canonical queue).

Creates the `outbox` table exactly as `bootstrap()` produced it today,
including the `outbox_created_idx` / `outbox_delivered_idx` indexes.
`IF NOT EXISTS` semantics: existing environments no-op. No data movement.

Parity with `bootstrap()` is asserted by
`tests/migrations/test_outbox_schema_parity.py`.

Forward-only: the repo posture has no downgrade path for schema-owning
migrations (see docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md,
the KERNEL-04 precedent this follows).

Revision ID: f3a1c9d2e4b7
Revises: 699c97b7c007
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "f3a1c9d2e4b7"
down_revision: Union[str, None] = "699c97b7c007"
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
        CREATE TABLE IF NOT EXISTS outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            topic TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            delivered_at TIMESTAMPTZ,
            attempts INT NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS outbox_created_idx ON outbox (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS outbox_delivered_idx ON outbox (delivered_at)")


def downgrade() -> None:
    raise RuntimeError(
        "KERNEL-05 outbox-schema migration is forward-only; the outbox table "
        "is the canonical runtime queue and is never dropped by downgrade."
    )
