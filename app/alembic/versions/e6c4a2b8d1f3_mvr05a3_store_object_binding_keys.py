"""MVR-05A3 (#4577): binding-key store projections and canonical child FKs.

The conversion is deliberately one forward-only transaction.  It locks every
parent and child in the supported mechanism, derives every binding from a
canonical parent, and refuses zero/many/cross-binding mappings before changing
keys or foreign keys.  PostgreSQL rolls an exception back together with all
earlier ADD COLUMN/backfill statements, leaving the old schema and rows intact.

Revision ID: e6c4a2b8d1f3
Revises: d1e8a0c5f37b
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e6c4a2b8d1f3"
down_revision: Union[str, None] = "d1e8a0c5f37b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
reversibility: str = "forward-only"


def upgrade() -> None:
    # Final fresh-create shapes are intentionally present even though the
    # supported revision chain already created these tables.  They are the
    # Alembic authority compared with STORE_SCHEMA_AUTOCREATE by the parity
    # harness, and make a missing test-fixture table converge without reviving
    # a global key.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.store_objects (
            object_id uuid NOT NULL,
            kind text NOT NULL,
            source_ref text,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            vault_binding_id text NOT NULL,
            PRIMARY KEY (vault_binding_id, object_id)
        );
        CREATE TABLE IF NOT EXISTS public.store_vector_index (
            object_id uuid NOT NULL,
            kind text NOT NULL,
            source_ref text,
            payload jsonb NOT NULL,
            embedding double precision[] NOT NULL,
            dim integer NOT NULL,
            model text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            provider text,
            normalize boolean,
            vault_binding_id text NOT NULL,
            PRIMARY KEY (vault_binding_id, object_id)
        );
        CREATE TABLE IF NOT EXISTS public.store_relations (
            src_id uuid NOT NULL,
            dst_id uuid NOT NULL,
            rel text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            vault_binding_id text NOT NULL,
            PRIMARY KEY (vault_binding_id, src_id, dst_id, rel)
        );
        CREATE TABLE IF NOT EXISTS public.store_relation_memberships (
            src_id uuid NOT NULL,
            rel text NOT NULL,
            value text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            vault_binding_id text NOT NULL,
            PRIMARY KEY (vault_binding_id, src_id, rel, value)
        );
        CREATE TABLE IF NOT EXISTS public.vector_index_meta (
            id integer NOT NULL CHECK (id = 1),
            identity_json text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            vault_binding_id text NOT NULL,
            PRIMARY KEY (vault_binding_id, id)
        );
        CREATE TABLE IF NOT EXISTS public.audit (
            id uuid PRIMARY KEY,
            object_id uuid,
            agent text NOT NULL,
            action text NOT NULL,
            ts timestamptz NOT NULL DEFAULT now(),
            trace_id text,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            vault_binding_id text
        )
        """
    )

    op.execute(
        """
        DO $mvr05a3$
        DECLARE
            unsupported text;
            missing text;
            offending text;
            current_pk text;
            fk record;
            action_update text;
            action_delete text;
            match_clause text;
            delete_columns text;
        BEGIN
            -- Promotion runs before the new producers start.  Keep the entire
            -- census/backfill/rekey against one stable population.
            LOCK TABLE
                public.objects,
                public.store_objects,
                public.store_vector_index,
                public.store_relations,
                public.store_relation_memberships,
                public.vector_index_meta,
                public.chunks,
                public.embeddings,
                public.relations,
                public.membership,
                public.decisions,
                public.audit
            IN SHARE ROW EXCLUSIVE MODE;

            -- Snapshot only after the conversion lock is held.  Taking this
            -- catalog census before the lock would leave a stale-inventory
            -- window for concurrent DDL on a supported child table.
            CREATE TEMP TABLE mvr05a3_fk_snapshot ON COMMIT DROP AS
            SELECT c.conname,
                   n.nspname AS table_schema,
                   t.relname AS table_name,
                   a.attname AS column_name,
                   parent_att.attname AS parent_column_name,
                   c.confupdtype,
                   c.confdeltype,
                   c.confmatchtype,
                   c.condeferrable,
                   c.condeferred
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid
               AND a.attnum = c.conkey[1]
              JOIN pg_attribute parent_att
                ON parent_att.attrelid = c.confrelid
               AND parent_att.attnum = c.confkey[1]
             WHERE c.contype = 'f'
               AND c.confrelid = 'public.store_objects'::regclass
               AND cardinality(c.conkey) = 1
               AND cardinality(c.confkey) = 1;

            IF EXISTS (
                SELECT 1
                  FROM pg_constraint c
                 WHERE c.contype = 'f'
                   AND c.confrelid = 'public.store_objects'::regclass
                   AND (cardinality(c.conkey) <> 1 OR cardinality(c.confkey) <> 1)
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'MVR-05A3 unsupported schema: pre-cutover store_objects FK is composite',
                    HINT = 'Inventory the live consumer and extend #4577 before retrying.';
            END IF;

            SELECT string_agg(
                       format('%I.%I.%I -> store_objects.%I',
                              table_schema, table_name, column_name, parent_column_name),
                       ', ' ORDER BY 1
                   )
              INTO unsupported
              FROM mvr05a3_fk_snapshot
             WHERE table_schema <> 'public'
                OR parent_column_name <> 'object_id'
                OR (table_name, column_name) NOT IN (
                 ('chunks', 'object_id'),
                 ('embeddings', 'object_id'),
                 ('relations', 'src_id'),
                 ('relations', 'dst_id'),
                 ('membership', 'object_id'),
                 ('membership', 'set_id'),
                 ('decisions', 'object_id'),
                 ('audit', 'object_id')
             );
            IF unsupported IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format('MVR-05A3 unaccounted store_objects FK consumer(s): %s', unsupported),
                    HINT = 'Do not weaken or drop it. Add a reviewed binding-key conversion and rerun.';
            END IF;

            -- Seven consumers are present on every supported lineage.
            -- membership.set_id is the eighth supported historical endpoint;
            -- on fresh databases it continues to reference sets(id).
            WITH required(table_name, column_name) AS (VALUES
                ('chunks', 'object_id'),
                ('embeddings', 'object_id'),
                ('relations', 'src_id'),
                ('relations', 'dst_id'),
                ('membership', 'object_id'),
                ('decisions', 'object_id'),
                ('audit', 'object_id')
            )
            SELECT string_agg(format('%I.%I', r.table_name, r.column_name), ', ' ORDER BY 1)
              INTO missing
             FROM required r
             WHERE (SELECT count(*) FROM mvr05a3_fk_snapshot s
                     WHERE s.table_schema = 'public'
                       AND s.parent_column_name = 'object_id'
                       AND (s.table_name, s.column_name) = (r.table_name, r.column_name)) <> 1;
            IF missing IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format('MVR-05A3 missing or duplicate supported store_objects FK(s): %s', missing),
                    HINT = 'Restore the #3510 canonical FK inventory, then rerun alembic upgrade head.';
            END IF;
            IF (SELECT count(*) FROM mvr05a3_fk_snapshot
                 WHERE table_schema = 'public'
                   AND parent_column_name = 'object_id'
                   AND table_name = 'membership' AND column_name = 'set_id') > 1 THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'MVR-05A3 duplicate historical membership.set_id store_objects FKs',
                    HINT = 'Reconcile the endpoint to one live FK, then rerun.';
            END IF;

            ALTER TABLE public.store_objects ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.store_vector_index ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.store_relations ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.store_relation_memberships ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.vector_index_meta ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.embeddings ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.relations ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.membership ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS vault_binding_id text;
            ALTER TABLE public.audit ADD COLUMN IF NOT EXISTS vault_binding_id text;

            -- Parent provenance is only objects.id -> objects.vault_binding_id.
            SELECT string_agg(s.object_id::text, ', ' ORDER BY s.object_id::text)
              INTO offending
              FROM public.store_objects s
              LEFT JOIN public.objects o ON o.id = s.object_id
             GROUP BY s.object_id
            HAVING count(o.*) = 0 OR count(DISTINCT o.vault_binding_id) <> 1
             LIMIT 20;
            IF offending IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format('MVR-05A3 store_objects binding backfill has zero/many parent mappings: %s', offending),
                    HINT = 'Reconcile objects.id continuity to exactly one source-backed binding and rerun.';
            END IF;
            UPDATE public.store_objects s
               SET vault_binding_id = source.vault_binding_id
              FROM (
                    SELECT id, min(vault_binding_id) AS vault_binding_id
                      FROM public.objects GROUP BY id
                   ) source
             WHERE source.id = s.object_id;

            -- Every derived store row must have exactly one canonical parent;
            -- multi-endpoint rows must resolve both endpoints to the same one.
            SELECT string_agg(v.object_id::text, ', ' ORDER BY v.object_id::text)
              INTO offending
              FROM public.store_vector_index v
              LEFT JOIN public.store_objects p ON p.object_id = v.object_id
             GROUP BY v.object_id
            HAVING count(DISTINCT p.vault_binding_id) <> 1
             LIMIT 20;
            IF offending IS NOT NULL THEN
                RAISE EXCEPTION USING MESSAGE = format(
                    'MVR-05A3 store_vector_index has zero/many canonical parents: %s', offending
                ), HINT = 'Reconcile or rebuild the named derived rows and rerun.';
            END IF;
            UPDATE public.store_vector_index v SET vault_binding_id = p.vault_binding_id
              FROM public.store_objects p WHERE p.object_id = v.object_id;

            SELECT string_agg(format('%s->%s', r.src_id, r.dst_id), ', ' ORDER BY 1)
              INTO offending
             FROM public.store_relations r
              LEFT JOIN public.store_objects src ON src.object_id = r.src_id
              LEFT JOIN public.store_objects dst ON dst.object_id = r.dst_id
             GROUP BY r.src_id, r.dst_id
            HAVING count(DISTINCT src.vault_binding_id) <> 1
                OR count(DISTINCT dst.vault_binding_id) <> 1
                OR min(src.vault_binding_id) IS DISTINCT FROM min(dst.vault_binding_id)
             LIMIT 20;
            IF offending IS NOT NULL THEN
                RAISE EXCEPTION USING MESSAGE = format(
                    'MVR-05A3 store_relations has zero/many/mismatched endpoint mappings: %s', offending
                ), HINT = 'Reconcile both endpoints to one source-backed binding and rerun.';
            END IF;
            UPDATE public.store_relations r SET vault_binding_id = src.vault_binding_id
              FROM public.store_objects src, public.store_objects dst
             WHERE src.object_id = r.src_id AND dst.object_id = r.dst_id
               AND src.vault_binding_id = dst.vault_binding_id;

            SELECT string_agg(format('%s/%s/%s', m.src_id, m.rel, m.value), ', ' ORDER BY 1)
              INTO offending
              FROM public.store_relation_memberships m
              LEFT JOIN public.store_objects p ON p.object_id = m.src_id
             GROUP BY m.src_id, m.rel, m.value
            HAVING count(DISTINCT p.vault_binding_id) <> 1
             LIMIT 20;
            IF offending IS NOT NULL THEN
                RAISE EXCEPTION USING MESSAGE = format(
                    'MVR-05A3 store_relation_memberships has zero/many canonical parents: %s', offending
                ), HINT = 'Reconcile the named source endpoints and rerun.';
            END IF;
            UPDATE public.store_relation_memberships m SET vault_binding_id = p.vault_binding_id
              FROM public.store_objects p WHERE p.object_id = m.src_id;

            -- The old singleton has no source of binding except its vectors.
            IF EXISTS (SELECT 1 FROM public.vector_index_meta) THEN
                IF NOT EXISTS (SELECT 1 FROM public.store_vector_index) THEN
                    RAISE EXCEPTION USING
                        MESSAGE = 'MVR-05A3 vector_index_meta singleton has no indexed row proving its binding',
                        HINT = 'Run the source-backed vector index rebuild, then rerun the migration.';
                END IF;
                IF (SELECT count(DISTINCT vault_binding_id) FROM public.store_vector_index) <> 1 THEN
                    RAISE EXCEPTION USING
                        MESSAGE = 'MVR-05A3 vector_index_meta singleton spans several vector bindings',
                        HINT = 'Run the source-backed vector index rebuild per binding, then rerun the migration.';
                END IF;
                UPDATE public.vector_index_meta
                   SET vault_binding_id = (SELECT min(vault_binding_id) FROM public.store_vector_index);
            END IF;

            -- Single-endpoint legacy children.
            FOR fk IN SELECT * FROM mvr05a3_fk_snapshot
                       WHERE table_name IN ('chunks', 'embeddings', 'decisions', 'audit')
                          OR (table_name = 'membership' AND column_name = 'object_id')
            LOOP
                EXECUTE format(
                    'SELECT string_agg(c.%1$I::text, '', '' ORDER BY c.%1$I::text) '
                    'FROM public.%2$I c LEFT JOIN public.store_objects p ON p.object_id = c.%1$I '
                    'WHERE c.%1$I IS NOT NULL GROUP BY c.%1$I '
                    'HAVING count(DISTINCT p.vault_binding_id) <> 1 LIMIT 20',
                    fk.column_name, fk.table_name
                ) INTO offending;
                IF offending IS NOT NULL THEN
                    RAISE EXCEPTION USING MESSAGE = format(
                        'MVR-05A3 %I.%I has zero/many canonical parents: %s',
                        fk.table_name, fk.column_name, offending
                    ), HINT = 'Reconcile each child reference to exactly one source-backed parent and rerun.';
                END IF;
                EXECUTE format(
                    'UPDATE public.%1$I c SET vault_binding_id = p.vault_binding_id '
                    'FROM public.store_objects p WHERE c.%2$I IS NOT NULL AND p.object_id = c.%2$I',
                    fk.table_name, fk.column_name
                );
            END LOOP;

            -- Relations share one binding across both live endpoints.
            SELECT string_agg(format('%s->%s', r.src_id, r.dst_id), ', ' ORDER BY 1)
              INTO offending
              FROM public.relations r
              LEFT JOIN public.store_objects src ON src.object_id = r.src_id
              LEFT JOIN public.store_objects dst ON dst.object_id = r.dst_id
             GROUP BY r.id, r.src_id, r.dst_id
            HAVING count(DISTINCT src.vault_binding_id) <> 1
                OR count(DISTINCT dst.vault_binding_id) <> 1
                OR min(src.vault_binding_id) IS DISTINCT FROM min(dst.vault_binding_id)
             LIMIT 20;
            IF offending IS NOT NULL THEN
                RAISE EXCEPTION USING MESSAGE = format(
                    'MVR-05A3 relations has zero/many/mismatched endpoint mappings: %s', offending
                ), HINT = 'Reconcile both endpoints to the same source-backed binding and rerun.';
            END IF;
            UPDATE public.relations r SET vault_binding_id = src.vault_binding_id
              FROM public.store_objects src, public.store_objects dst
             WHERE src.object_id = r.src_id AND dst.object_id = r.dst_id
               AND src.vault_binding_id = dst.vault_binding_id;

            -- Historical membership has two canonical endpoints; fresh
            -- membership.set_id -> sets(id) remains untouched.
            IF EXISTS (SELECT 1 FROM mvr05a3_fk_snapshot
                        WHERE table_name = 'membership' AND column_name = 'set_id') THEN
                SELECT string_agg(format('%s->%s', m.object_id, m.set_id), ', ' ORDER BY 1)
                  INTO offending
                  FROM public.membership m
                  LEFT JOIN public.store_objects obj ON obj.object_id = m.object_id
                  LEFT JOIN public.store_objects set_obj ON set_obj.object_id = m.set_id
                 GROUP BY m.object_id, m.set_id
                HAVING count(DISTINCT obj.vault_binding_id) <> 1
                    OR count(DISTINCT set_obj.vault_binding_id) <> 1
                    OR min(obj.vault_binding_id) IS DISTINCT FROM min(set_obj.vault_binding_id)
                 LIMIT 20;
                IF offending IS NOT NULL THEN
                    RAISE EXCEPTION USING MESSAGE = format(
                        'MVR-05A3 historical membership has zero/many/mismatched endpoints: %s', offending
                    ), HINT = 'Reconcile object_id and set_id to one source-backed binding and rerun.';
                END IF;
            END IF;

            -- Nullable receipts may be unbound only when they already have no
            -- object reference.  Non-null references were filled above.
            IF EXISTS (SELECT 1 FROM public.decisions
                        WHERE object_id IS NOT NULL AND vault_binding_id IS NULL)
               OR EXISTS (SELECT 1 FROM public.audit
                          WHERE object_id IS NOT NULL AND vault_binding_id IS NULL) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'MVR-05A3 nullable receipt backfill left a non-null reference without binding',
                    HINT = 'Reconcile the named canonical parent and rerun.';
            END IF;

            -- Remove old inbound constraints before removing the one-column
            -- unique parent key they depend on.
            FOR fk IN SELECT * FROM mvr05a3_fk_snapshot LOOP
                EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I',
                               fk.table_schema, fk.table_name, fk.conname);
            END LOOP;

            -- Binding columns are now proven.  Store rows and non-null child
            -- endpoint groups cannot omit their namespace after cutover.
            ALTER TABLE public.store_objects ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.store_vector_index ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.store_relations ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.store_relation_memberships ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.vector_index_meta ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.chunks ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.embeddings ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.relations ALTER COLUMN vault_binding_id SET NOT NULL;
            ALTER TABLE public.membership ALTER COLUMN vault_binding_id SET NOT NULL;

            -- Replace each store identity.  There is intentionally no default:
            -- every producer must name its binding explicitly.
            FOR offending, current_pk IN
                SELECT table_name, constraint_name
                  FROM information_schema.table_constraints
                 WHERE table_schema = 'public'
                   AND table_name IN ('store_objects', 'store_vector_index', 'store_relations',
                                      'store_relation_memberships', 'vector_index_meta')
                   AND constraint_type = 'PRIMARY KEY'
            LOOP
                EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', offending, current_pk);
            END LOOP;
            ALTER TABLE public.store_objects ADD CONSTRAINT store_objects_pkey
                PRIMARY KEY (vault_binding_id, object_id);
            ALTER TABLE public.store_vector_index ADD CONSTRAINT store_vector_index_pkey
                PRIMARY KEY (vault_binding_id, object_id);
            ALTER TABLE public.store_relations ADD CONSTRAINT store_relations_pkey
                PRIMARY KEY (vault_binding_id, src_id, dst_id, rel);
            ALTER TABLE public.store_relation_memberships ADD CONSTRAINT store_relation_memberships_pkey
                PRIMARY KEY (vault_binding_id, src_id, rel, value);
            ALTER TABLE public.vector_index_meta ADD CONSTRAINT vector_index_meta_pkey
                PRIMARY KEY (vault_binding_id, id);

            -- Remove any independently-created one-column uniqueness which
            -- would silently retain the cross-binding collision.
            FOR fk IN
                SELECT c.conname, n.nspname AS table_schema, t.relname AS table_name
                  FROM pg_constraint c
                  JOIN pg_class t ON t.oid = c.conrelid
                  JOIN pg_namespace n ON n.oid = t.relnamespace
                 WHERE c.conrelid = 'public.store_objects'::regclass
                   AND c.contype = 'u'
                   AND (SELECT array_agg(a.attname::text ORDER BY k.ordinality)
                          FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality)
                          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum)
                       = ARRAY['object_id']::text[]
            LOOP
                EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I',
                               fk.table_schema, fk.table_name, fk.conname);
            END LOOP;
            FOR fk IN
                SELECT indexrelid::regclass::text AS conname
                  FROM pg_index
                 WHERE indrelid = 'public.store_objects'::regclass
                   AND indisunique AND NOT indisprimary
                   AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = indexrelid)
                   AND (SELECT array_agg(a.attname::text ORDER BY k.ordinality)
                          FROM unnest(indkey::smallint[]) WITH ORDINALITY k(attnum, ordinality)
                          JOIN pg_attribute a ON a.attrelid = indrelid AND a.attnum = k.attnum)
                       = ARRAY['object_id']::text[]
            LOOP
                EXECUTE format('DROP INDEX %s', fk.conname);
            END LOOP;

            ALTER TABLE public.decisions ADD CONSTRAINT decisions_object_binding_check
                CHECK (object_id IS NULL OR vault_binding_id IS NOT NULL);
            ALTER TABLE public.audit ADD CONSTRAINT audit_object_binding_check
                CHECK (object_id IS NULL OR vault_binding_id IS NOT NULL);

            -- Restore each supported FK with the original semantics.  For
            -- nullable receipts PostgreSQL's column-list SET NULL preserves
            -- vault_binding_id while clearing only object_id.
            FOR fk IN SELECT * FROM mvr05a3_fk_snapshot ORDER BY table_name, column_name LOOP
                action_update := CASE fk.confupdtype
                    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT' END;
                action_delete := CASE fk.confdeltype
                    WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT' END;
                match_clause := CASE fk.confmatchtype
                    WHEN 'f' THEN 'MATCH FULL' WHEN 'p' THEN 'MATCH PARTIAL' ELSE 'MATCH SIMPLE' END;
                delete_columns := CASE
                    WHEN fk.table_name IN ('decisions', 'audit') AND fk.confdeltype = 'n'
                    THEN format(' (%I)', fk.column_name) ELSE '' END;
                EXECUTE format(
                    'ALTER TABLE %I.%I ADD CONSTRAINT %I '
                    'FOREIGN KEY (vault_binding_id, %I) '
                    'REFERENCES public.store_objects(vault_binding_id, object_id) %s '
                    'ON UPDATE %s ON DELETE %s%s %s %s',
                    fk.table_schema, fk.table_name, fk.conname, fk.column_name,
                    match_clause, action_update, action_delete, delete_columns,
                    CASE WHEN fk.condeferrable THEN 'DEFERRABLE' ELSE 'NOT DEFERRABLE' END,
                    CASE WHEN fk.condeferred THEN 'INITIALLY DEFERRED' ELSE 'INITIALLY IMMEDIATE' END
                );
            END LOOP;

            CREATE INDEX IF NOT EXISTS chunks_object_binding_idx
                ON public.chunks(vault_binding_id, object_id);
            CREATE INDEX IF NOT EXISTS embeddings_object_binding_idx
                ON public.embeddings(vault_binding_id, object_id);
            CREATE INDEX IF NOT EXISTS relations_src_binding_idx
                ON public.relations(vault_binding_id, src_id);
            CREATE INDEX IF NOT EXISTS relations_dst_binding_idx
                ON public.relations(vault_binding_id, dst_id);
            CREATE INDEX IF NOT EXISTS membership_object_binding_idx
                ON public.membership(vault_binding_id, object_id);
            CREATE INDEX IF NOT EXISTS decisions_object_binding_idx
                ON public.decisions(vault_binding_id, object_id);
            CREATE INDEX IF NOT EXISTS audit_object_binding_idx
                ON public.audit(vault_binding_id, object_id);
            CREATE INDEX IF NOT EXISTS ix_store_vector_index_content_hash
                ON public.store_vector_index ((payload ->> 'content_hash'));
        END
        $mvr05a3$;
        """
    )
def downgrade() -> None:
    raise RuntimeError(
        "MVR-05A3 (#4577) is forward-only: removing binding identity would merge "
        "namespaces and cannot be automated safely. Roll forward with a reviewed recovery migration."
    )
