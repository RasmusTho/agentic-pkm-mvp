"""#3488: make the active decisions writer schema migration-owned.

Revision ID: e1d2c3b4a5f6
Revises: 4d1e0c9a3329

The legacy ``PgDecisions`` runtime path used to create and alter this table on
write. This forward-only migration carries that operational shape into Alembic
so a missing or stale schema fails loudly with a migration instruction instead
of being changed by application traffic.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e1d2c3b4a5f6"
down_revision: Union[str, None] = "4d1e0c9a3329"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        CREATE TABLE IF NOT EXISTS public.decisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            object_id uuid REFERENCES public.objects(id) ON DELETE SET NULL,
            agent text,
            kind text,
            key text NOT NULL,
            value jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS agent text;
        ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS kind text;
        ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE public.decisions ALTER COLUMN id SET DEFAULT gen_random_uuid();
        ALTER TABLE public.decisions ALTER COLUMN object_id DROP NOT NULL;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            fk_name text;
            delete_rule text;
        BEGIN
            SELECT tc.constraint_name, rc.delete_rule INTO fk_name, delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
             AND rc.constraint_schema = tc.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = 'decisions'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'object_id'
            LIMIT 1;

            IF fk_name IS NOT NULL AND delete_rule IS DISTINCT FROM 'SET NULL' THEN
                EXECUTE format('ALTER TABLE public.decisions DROP CONSTRAINT %I', fk_name);
            END IF;

            IF fk_name IS NULL OR delete_rule IS DISTINCT FROM 'SET NULL' THEN
                ALTER TABLE public.decisions
                    ADD CONSTRAINT decisions_object_id_fkey
                    FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE SET NULL;
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Decisions schema migration (#3488) is forward-only; downgrading would return "
        "schema authority to runtime writes."
    )
