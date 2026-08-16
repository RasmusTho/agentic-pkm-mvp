"""MVR-05A7: bind outbox rows and preserve scalar-era dedup history.

The scalar outbox persisted only its derived UUID primary key, not the source
identity or content fingerprint used to derive it.  This revision therefore
copies, and never recomputes, that key into ``legacy_key``.  Plain scalar-era
rows belong to the one explicit compatibility binding.  A partially upgraded
row whose ``legacy_key`` already differs from ``id`` but lacks a binding is
unprovable and receives the fail-safe quarantine marker.
"""

from alembic import op


revision = "f6a05a7b0001"
down_revision = "f5a05a5b0001"
branch_labels = None
depends_on = None
reversibility = "forward-only"

_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"
_QUARANTINE_BINDING_ID = "outbox-quarantined-unprovable-binding"


def upgrade() -> None:
    op.execute(
        f"""
        LOCK TABLE public.outbox IN SHARE ROW EXCLUSIVE MODE;

        ALTER TABLE public.outbox
          ADD COLUMN IF NOT EXISTS vault_binding_id text;
        ALTER TABLE public.outbox
          ADD COLUMN IF NOT EXISTS legacy_key uuid;

        -- A partially upgraded scoped row cannot be attributed from the
        -- stored envelope.  Preserve it as collision evidence; never guess.
        UPDATE public.outbox
           SET vault_binding_id = '{_QUARANTINE_BINDING_ID}'
         WHERE vault_binding_id IS NULL
           AND legacy_key IS NOT NULL
           AND legacy_key <> id;
        UPDATE public.outbox
           SET vault_binding_id = '{_QUARANTINE_BINDING_ID}'
         WHERE vault_binding_id IS NOT NULL
           AND btrim(vault_binding_id) = '';

        -- This is deliberately a copy.  The original derivation inputs do not
        -- exist on the row and key rewriting is structurally impossible.
        UPDATE public.outbox
           SET legacy_key = id
         WHERE legacy_key IS NULL;

        -- Every remaining unclassified row is a plain scalar-era row from the
        -- one compatibility binding established by the preceding MVR slices.
        UPDATE public.outbox
           SET vault_binding_id = '{_COMPATIBILITY_BINDING_ID}'
         WHERE vault_binding_id IS NULL;

        ALTER TABLE public.outbox
          ALTER COLUMN vault_binding_id
          SET DEFAULT '{_COMPATIBILITY_BINDING_ID}';
        ALTER TABLE public.outbox
          ALTER COLUMN vault_binding_id SET NOT NULL;

        """
    )


def downgrade() -> None:
    raise RuntimeError("MVR-05A7 outbox binding and dual-key history are forward-only")
