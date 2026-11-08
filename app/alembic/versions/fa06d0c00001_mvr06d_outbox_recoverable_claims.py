"""MVR-06D: recoverable PostgreSQL claims for the many-binding outbox dispatch.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D). Before more than one
production worker lifecycle dispatches the outbox, each row needs at most one concurrent
claim owner through an atomic recoverable database lease rather than a plain select
followed by a later acknowledgement. This revision adds only nullable columns, a CHECK on
the claim phase, a monotonic fencing-token sequence, and one partial index; no existing
row is rewritten, so every pre-MVR-06D row stays unclaimed and keeps its ``id``,
``legacy_key``, and ``vault_binding_id`` lineage.

- ``claim_token`` / ``claim_owner`` / ``claim_expires_at`` / ``claim_phase``: the
  database-monotonic fencing token and lease of the current claim. ``claim_phase`` is
  ``claimed`` -> ``effect_pending`` (persisted with the token, binding, idempotency
  identity, and bounded ``effect_descriptor`` *before* the handler runs) or
  ``effect_reconciliation_required`` (an ambiguous post-crash outcome that blocks).
- ``effect_outcome`` / ``effect_receipt``: written inside the same token-checked store
  transaction as the admitted handler's effect, so recovery can prove applied (present)
  or not applied (absent) before any current-authority quarantine.
- ``consumer_context``: the consumer ActiveContextSet generation linked to the row's
  immutable producer context.
- ``quarantined_at`` / ``quarantine_reason``: the terminal, observable quarantine
  disposition of an unsafe vault-bound row; the row keeps its binding.

The queue-state fields are written only by an MVR-06D runtime after the registry
``minimumRuntimeSchema=mvr-06d`` floor commits; the columns themselves are inert DDL.
Forward-only: no downgrade may discard or reinterpret claim/reconciliation state.

Revision ID: fa06d0c00001
Revises: c9d0e1f2a3b4
"""

from typing import Sequence, Union

from alembic import op

revision: str = "fa06d0c00001"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE SEQUENCE IF NOT EXISTS public.outbox_claim_token_seq AS bigint;

        ALTER TABLE public.outbox
          ADD COLUMN IF NOT EXISTS claim_token bigint,
          ADD COLUMN IF NOT EXISTS claim_owner text,
          ADD COLUMN IF NOT EXISTS claim_expires_at timestamptz,
          ADD COLUMN IF NOT EXISTS claim_phase text,
          ADD COLUMN IF NOT EXISTS effect_descriptor jsonb,
          ADD COLUMN IF NOT EXISTS effect_outcome text,
          ADD COLUMN IF NOT EXISTS effect_receipt jsonb,
          ADD COLUMN IF NOT EXISTS consumer_context jsonb,
          ADD COLUMN IF NOT EXISTS quarantined_at timestamptz,
          ADD COLUMN IF NOT EXISTS quarantine_reason text;

        ALTER TABLE public.outbox DROP CONSTRAINT IF EXISTS outbox_claim_phase_check;
        ALTER TABLE public.outbox ADD CONSTRAINT outbox_claim_phase_check CHECK (
          claim_phase IS NULL
          OR (
            claim_phase IN ('claimed', 'effect_pending', 'effect_reconciliation_required')
            AND claim_token IS NOT NULL
            AND claim_owner IS NOT NULL
            AND claim_expires_at IS NOT NULL
          )
        );
        ALTER TABLE public.outbox DROP CONSTRAINT IF EXISTS outbox_effect_outcome_check;
        ALTER TABLE public.outbox ADD CONSTRAINT outbox_effect_outcome_check CHECK (
          effect_outcome IS NULL OR effect_outcome IN ('applied', 'no_effect')
        );

        CREATE INDEX IF NOT EXISTS outbox_claimable_idx
          ON public.outbox (vault_binding_id, created_at)
          WHERE delivered_at IS NULL AND quarantined_at IS NULL;
        """
    )


def downgrade() -> None:
    raise RuntimeError("MVR-06D recoverable outbox claim state is forward-only")
