"""#3510: move live legacy-object FKs to canonical store_objects.

The migration is deliberately forward-only.  It refuses unknown consumers and
rows whose referenced id has not first been materialized in ``store_objects``;
operators must repair/backfill those rows and rerun the migration rather than
silently losing history.

Revision ID: 7e4f2a1c9d30
Revises: 4d1e0c9a3329
"""

from typing import Sequence, Union

from alembic import op


revision: str = "7e4f2a1c9d30"
down_revision: Union[str, None] = "4d1e0c9a3329"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"

# Every schema shape observed in the supported migration lineage.  ``set_id``
# points at ``sets`` on fresh databases, but some retained v4.5 databases used
# objects-as-sets; accepting it here keeps that live historical shape explicit.
LEGACY_OBJECTS_FK_CONSUMERS = frozenset(
    {
        ("chunks", "object_id"),
        ("embeddings", "object_id"),
        ("relations", "src_id"),
        ("relations", "dst_id"),
        ("membership", "object_id"),
        ("membership", "set_id"),
        ("decisions", "object_id"),
        ("audit", "object_id"),
    }
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            fk record;
            orphan_count bigint;
            delete_action text;
            update_action text;
            source_expression text;
            updated_expression text;
        BEGIN
            IF to_regclass('public.objects') IS NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported schema: public.objects is missing',
                    HINT = 'Restore the expected pre-migration schema, then rerun alembic upgrade head.';
            END IF;
            IF to_regclass('public.store_objects') IS NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported schema: public.store_objects is missing',
                    HINT = 'Run the store-schema migrations before retrying this migration.';
            END IF;

            -- Promotion applies migrations before restarting the old runtime.
            -- Hold both producer tables against concurrent writes for the full
            -- preflight/backfill/FK-cutover transaction so the retained-row
            -- census cannot change underneath the snapshot.
            LOCK TABLE public.objects, public.store_objects IN SHARE ROW EXCLUSIVE MODE;

            IF EXISTS (
                SELECT 1
                FROM public.objects
                WHERE uuid IS NOT NULL
                GROUP BY uuid
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported data: duplicate non-null objects.uuid values',
                    HINT = 'Reconcile each retained vault UUID to exactly one objects.id, then rerun alembic upgrade head.';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM public.objects legacy
                JOIN public.store_objects canonical
                  ON canonical.object_id = legacy.uuid
                WHERE legacy.uuid IS NOT NULL
                  AND legacy.id IS DISTINCT FROM legacy.uuid
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported data: retained vault UUID already names a different canonical object',
                    HINT = 'Reconcile the store_objects row keyed by objects.uuid with the retained objects.id identity, then rerun alembic upgrade head.';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM public.objects legacy
                JOIN public.objects canonical
                  ON canonical.id = legacy.uuid
                 AND canonical.id IS DISTINCT FROM legacy.id
                WHERE legacy.uuid IS NOT NULL
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported data: retained vault UUID collides with another objects.id',
                    HINT = 'Reconcile the cross-key alias so every retained UUID names only its own canonical objects.id, then rerun alembic upgrade head.';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint c
                WHERE c.contype = 'f'
                  AND c.confrelid = 'public.objects'::regclass
                  AND (cardinality(c.conkey) <> 1 OR cardinality(c.confkey) <> 1)
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported schema: composite FK references public.objects',
                    HINT = 'Inventory this live consumer and extend the reviewed migration strategy before retrying.';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_attribute referenced
                  ON referenced.attrelid = c.confrelid
                 AND referenced.attnum = c.confkey[1]
                WHERE c.contype = 'f'
                  AND c.confrelid = 'public.objects'::regclass
                  AND cardinality(c.conkey) = 1
                  AND cardinality(c.confkey) = 1
                  AND referenced.attname <> 'id'
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = '#3510 unsupported schema: objects FK must reference objects.id',
                    HINT = 'Inventory this live consumer and add a reviewed child-key translation before retrying.';
            END IF;

            -- Existing-resource producer: materialize every retained legacy object
            -- in the canonical store before any FK is moved.  Existing canonical
            -- rows win; the legacy row is a continuity source, never a second
            -- writer after this migration.
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'objects'
                  AND column_name = 'source_ref'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'objects'
                  AND column_name = 'path'
            ) THEN
                -- Reviewed row-level precedence: an explicit source_ref wins;
                -- the watcher path supplies the locator when source_ref is NULL.
                -- If both are NULL the canonical locator remains NULL.
                source_expression := 'COALESCE(source_ref, path)';
            ELSIF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'objects'
                  AND column_name = 'source_ref'
            ) THEN
                source_expression := 'source_ref';
            ELSIF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'objects'
                  AND column_name = 'path'
            ) THEN
                source_expression := 'path';
            ELSE
                source_expression := 'NULL::text';
            END IF;

            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'objects' AND column_name = 'updated_at') THEN
                updated_expression := 'COALESCE(updated_at, created_at, now())';
            ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'objects' AND column_name = 'created_at') THEN
                updated_expression := 'COALESCE(created_at, now())';
            ELSE
                updated_expression := 'now()';
            END IF;

            EXECUTE format(
                'INSERT INTO public.store_objects '
                || '(object_id, kind, source_ref, payload, created_at, updated_at) '
                || 'SELECT id, COALESCE(kind, ''legacy''), %s, '
                || 'COALESCE(payload::jsonb, ''{}''::jsonb), COALESCE(created_at, now()), '
                || '%s FROM public.objects '
                || 'ON CONFLICT (object_id) DO NOTHING',
                source_expression, updated_expression
            );

            FOR fk IN
                SELECT c.oid,
                       c.conname,
                       n.nspname AS table_schema,
                       t.relname AS table_name,
                       a.attname AS column_name,
                       c.confdeltype,
                       c.confupdtype,
                       c.condeferrable,
                       c.condeferred
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid
                 AND a.attnum = c.conkey[1]
                WHERE c.contype = 'f'
                  AND c.confrelid = 'public.objects'::regclass
                  AND cardinality(c.conkey) = 1
                  AND cardinality(c.confkey) = 1
                ORDER BY t.relname, a.attname
            LOOP
                IF fk.table_schema <> 'public'
                   OR (fk.table_name, fk.column_name) NOT IN (
                       ('chunks', 'object_id'),
                       ('embeddings', 'object_id'),
                       ('relations', 'src_id'),
                       ('relations', 'dst_id'),
                       ('membership', 'object_id'),
                       ('membership', 'set_id'),
                       ('decisions', 'object_id'),
                       ('audit', 'object_id')
                   ) THEN
                    RAISE EXCEPTION USING
                        MESSAGE = format(
                            '#3510 unsupported schema: unaccounted objects FK %I.%I(%I)',
                            fk.table_schema, fk.table_name, fk.column_name
                        ),
                        HINT = 'Inventory this live consumer and extend the reviewed migration strategy before retrying.';
                END IF;

                EXECUTE format(
                    'SELECT count(*) FROM %I.%I child '
                    'WHERE child.%I IS NOT NULL AND NOT EXISTS ('
                    'SELECT 1 FROM public.store_objects parent '
                    'WHERE parent.object_id = child.%I)',
                    fk.table_schema, fk.table_name, fk.column_name, fk.column_name
                ) INTO orphan_count;

                IF orphan_count > 0 THEN
                    RAISE EXCEPTION USING
                        MESSAGE = format(
                            '#3510 migration blocked: %s row(s) in %I.%I.%I lack a canonical store_objects parent',
                            orphan_count, fk.table_schema, fk.table_name, fk.column_name
                        ),
                        HINT = 'Backfill or reconcile the missing store_objects rows from the vault/continuity source, verify the count is zero, then rerun alembic upgrade head.';
                END IF;

                delete_action := CASE fk.confdeltype
                    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END;
                update_action := CASE fk.confupdtype
                    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END;

                EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I',
                               fk.table_schema, fk.table_name, fk.conname);
                EXECUTE format(
                    'ALTER TABLE %I.%I ADD CONSTRAINT %I FOREIGN KEY (%I) '
                    'REFERENCES public.store_objects(object_id) ON UPDATE %s ON DELETE %s %s %s',
                    fk.table_schema, fk.table_name, fk.conname, fk.column_name,
                    update_action, delete_action,
                    CASE WHEN fk.condeferrable THEN 'DEFERRABLE' ELSE 'NOT DEFERRABLE' END,
                    CASE WHEN fk.condeferred THEN 'INITIALLY DEFERRED' ELSE 'INITIALLY IMMEDIATE' END
                );
            END LOOP;
        END$$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "#3510 is forward-only: restoring legacy objects FK ownership requires an explicit "
        "reviewed recovery migration after recreating every compatibility parent."
    )
