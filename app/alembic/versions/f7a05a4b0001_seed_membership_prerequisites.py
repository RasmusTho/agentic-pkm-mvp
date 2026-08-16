"""Seed the named-set prerequisites consumed by membership projection.

Fresh membership rows reference ``sets(id)``.  The retained historical
lineage references the same UUID through binding-scoped ``store_objects``.
This revision seeds both producers without weakening the runtime refusal when
either prerequisite is later removed.
"""

from alembic import op


revision = "f7a05a4b0001"
down_revision = "f6a05a7b0001"
branch_labels = None
depends_on = None
reversibility = "forward-only"

_PUBLISHED_SET_ID = "afa60fd2-731a-5c30-ae25-07f56c115393"
_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"


def upgrade() -> None:
    op.execute(
        f"""
        DO $membership_prerequisites$
        DECLARE
          membership_columns text[];
          published_set_id uuid;
        BEGIN
          IF to_regclass('public.sets') IS NULL
             OR to_regclass('public.store_objects') IS NULL
             OR to_regclass('public.membership') IS NULL THEN
            RAISE EXCEPTION USING
              MESSAGE = 'membership prerequisite migration requires sets, store_objects, and membership',
              HINT = 'Restore the supported migration lineage, then rerun alembic upgrade head.';
          END IF;

          LOCK TABLE public.sets, public.store_objects, public.membership
            IN SHARE ROW EXCLUSIVE MODE;

          SELECT array_agg(a.attname ORDER BY key.ordinality)
            INTO membership_columns
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY key(attnum, ordinality) ON true
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=key.attnum
           WHERE c.conrelid='public.membership'::regclass AND c.contype='p';

          IF membership_columns = ARRAY['vault_binding_id','id']::text[] THEN
            IF NOT EXISTS (
              SELECT 1 FROM pg_constraint c
               WHERE c.contype='f' AND c.conrelid='public.membership'::regclass
                 AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
                   WHERE attrelid='public.membership'::regclass AND attname='set_id'
                     AND attnum>0 AND NOT attisdropped)]::smallint[]
                 AND c.confrelid='public.sets'::regclass
                 AND c.confkey=ARRAY[(SELECT attnum FROM pg_attribute
                   WHERE attrelid='public.sets'::regclass AND attname='id'
                     AND attnum>0 AND NOT attisdropped)]::smallint[]
            ) THEN
              RAISE EXCEPTION USING
                MESSAGE = 'membership prerequisite migration found an unsupported fresh set endpoint',
                HINT = 'Repair membership.set_id to reference sets(id), then rerun.';
            END IF;
          ELSIF membership_columns = ARRAY['vault_binding_id','object_id','set_id']::text[] THEN
            IF NOT EXISTS (
              SELECT 1 FROM pg_constraint c
               WHERE c.contype='f' AND c.conrelid='public.membership'::regclass
                 AND c.conkey=ARRAY[
                   (SELECT attnum FROM pg_attribute WHERE attrelid='public.membership'::regclass
                     AND attname='vault_binding_id' AND attnum>0 AND NOT attisdropped),
                   (SELECT attnum FROM pg_attribute WHERE attrelid='public.membership'::regclass
                     AND attname='set_id' AND attnum>0 AND NOT attisdropped)
                 ]::smallint[]
                 AND c.confrelid='public.store_objects'::regclass
                 AND c.confkey=ARRAY[
                   (SELECT attnum FROM pg_attribute WHERE attrelid='public.store_objects'::regclass
                     AND attname='vault_binding_id' AND attnum>0 AND NOT attisdropped),
                   (SELECT attnum FROM pg_attribute WHERE attrelid='public.store_objects'::regclass
                     AND attname='object_id' AND attnum>0 AND NOT attisdropped)
                 ]::smallint[]
            ) THEN
              RAISE EXCEPTION USING
                MESSAGE = 'membership prerequisite migration found an unsupported retained set endpoint',
                HINT = 'Repair the binding-scoped membership.set_id endpoint, then rerun.';
            END IF;
          ELSE
            RAISE EXCEPTION USING
              MESSAGE = 'membership prerequisite migration found an unsupported primary-key lineage',
              HINT = 'Repair to a supported MVR-05A4 membership shape, then rerun.';
          END IF;

          INSERT INTO public.sets (id, name, meta)
          VALUES ('{_PUBLISHED_SET_ID}'::uuid, 'published',
                  '{{"system":"membership-projection"}}'::jsonb)
          ON CONFLICT (name) DO NOTHING;

          SELECT id INTO published_set_id FROM public.sets WHERE name='published';
          IF published_set_id IS NULL THEN
            RAISE EXCEPTION USING
              MESSAGE = 'membership prerequisite migration could not seed the published set';
          END IF;

          IF membership_columns = ARRAY['vault_binding_id','object_id','set_id']::text[] THEN
            INSERT INTO public.store_objects
              (vault_binding_id, object_id, kind, source_ref, payload)
            VALUES
              ('{_COMPATIBILITY_BINDING_ID}', published_set_id, 'membership-set', NULL,
               '{{"name":"published","registry":"sets"}}'::jsonb)
            ON CONFLICT (vault_binding_id, object_id) DO NOTHING;

            IF NOT EXISTS (
              SELECT 1 FROM public.store_objects
               WHERE vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
                 AND object_id=published_set_id
            ) THEN
              RAISE EXCEPTION USING
                MESSAGE = 'membership prerequisite migration could not seed the retained published endpoint';
            END IF;
          END IF;
        END $membership_prerequisites$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("membership prerequisite seed is forward-only")
