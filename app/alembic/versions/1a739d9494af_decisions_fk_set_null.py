"""#2788: decisions.object_id FK CASCADE -> SET NULL (mirrors audit.object_id).

`decisions.object_id` was `ON DELETE CASCADE` (`202510241200_sot41_amg_core.py:87`)
while the sibling canonical log `audit.object_id` is `ON DELETE SET NULL`
(`:104`). Two canonical append-only logs had opposite object-cleanup loss
semantics: if object cleanup ever lands (owner decision D-2 on #2778),
decisions history would silently vanish instead of surviving with a NULL
`object_id`, unlike `audit`. This migration realigns `decisions` to the
`audit` posture: the FK becomes `ON DELETE SET NULL` and the column becomes
nullable so the FK action is legal.

The FK constraint name varies across the historical migration lineage
(`202510241200_sot41_amg_core.py`, `a80043832e29_v4_5_baseline_stores_decisions_.py`,
and the runtime `_ensure_decisions()` helper in `app/stores/postgres.py` all
`CREATE TABLE IF NOT EXISTS decisions` with an unnamed inline
`REFERENCES objects(id) ON DELETE CASCADE`, so Postgres assigns the
constraint name from whichever `CREATE TABLE` actually ran first). This
migration resolves the FK constraint name dynamically from the catalog
instead of hardcoding one, then drops and recreates it with `ON DELETE SET
NULL`.

Forward-only: no downgrade path (see docs/architecture/runtime-semantics.md
:: Divergences, D-5/D-7 follow-up). Downgrading would silently reintroduce
the cascade-delete data-loss hazard this migration removes.
"""

from alembic import op

# Alembic identifiers
revision = "1a739d9494af"
down_revision = "c2766a04d001"

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility = "forward-only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            fk_name text;
        BEGIN
            SELECT tc.constraint_name INTO fk_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = 'decisions'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'object_id'
            LIMIT 1;

            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.decisions DROP CONSTRAINT %I', fk_name);
            END IF;

            ALTER TABLE public.decisions ALTER COLUMN object_id DROP NOT NULL;

            ALTER TABLE public.decisions
                ADD CONSTRAINT decisions_object_id_fkey
                FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE SET NULL;
        END$$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "decisions FK CASCADE->SET NULL migration (#2788) is forward-only; "
        "downgrading would silently reintroduce the cascade-delete data-loss "
        "hazard (D-5) this migration removes."
    )
