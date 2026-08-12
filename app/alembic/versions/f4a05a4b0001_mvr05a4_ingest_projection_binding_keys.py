"""MVR-05A4: finish binding keys for the four ingest projections.

The preceding MVR-05A3 revision owns binding attribution and the canonical
``store_objects`` foreign keys.  This revision deliberately does neither
again: it only derives the *existing* membership key and the live chunk
consumer from PostgreSQL's catalog, then makes those identities binding-safe.
Unsupported catalog state is a refusal, before any DDL or row mutation.
"""

from alembic import op


revision = "f4a05a4b0001"
down_revision = "e6c4a2b8d1f3"
branch_labels = None
depends_on = None
reversibility = "forward-only"


def upgrade() -> None:
    op.execute(
        r"""
        DO $mvr05a4$
        DECLARE
          membership_pk text;
          membership_columns text[];
          chunk_fk record;
          membership_fk record;
          bad text;
          update_action text;
          delete_action text;
          match_clause text;
          deferrable_clause text;
        BEGIN
          -- One conversion census and lock: no writer/DDL can make the catalog
          -- lie between the shape check and the replacement constraints.
          LOCK TABLE public.chunks, public.embeddings, public.relations,
                     public.membership IN SHARE ROW EXCLUSIVE MODE;

          SELECT conname, array_agg(a.attname ORDER BY key.ordinality)
            INTO membership_pk, membership_columns
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY key(attnum, ordinality) ON true
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = key.attnum
           WHERE c.conrelid = 'public.membership'::regclass AND c.contype = 'p'
           GROUP BY conname;
          IF membership_columns = ARRAY['id']::text[] THEN
            NULL; -- fresh 202510241200 lineage
          ELSIF membership_columns = ARRAY['object_id','set_id']::text[] THEN
            NULL; -- retained historical a80043832e29 lineage
          ELSE
            RAISE EXCEPTION USING
              MESSAGE = 'MVR-05A4 unsupported membership primary-key lineage',
              HINT = 'Repair to the supported fresh id or historical (object_id,set_id) shape and rerun.';
          END IF;

          -- Every effective inbound FK is enumerated before changing a key.
          SELECT c.conname, c.confupdtype, c.confdeltype, c.confmatchtype,
                 c.condeferrable, c.condeferred
            INTO chunk_fk
            FROM pg_constraint c
           WHERE c.contype = 'f' AND c.conrelid = 'public.embeddings'::regclass
             AND c.confrelid = 'public.chunks'::regclass
             AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid='public.embeddings'::regclass
                                      AND attname='chunk_id' AND NOT attisdropped)]::smallint[]
             AND c.confkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid='public.chunks'::regclass
                                      AND attname='id' AND NOT attisdropped)]::smallint[];
          IF NOT FOUND THEN
            RAISE EXCEPTION USING
              MESSAGE = 'MVR-05A4 missing or unsupported embeddings.chunk_id inbound FK',
              HINT = 'Do not infer a consumer; repair its catalog shape and rerun.';
          END IF;
          SELECT string_agg(conname, ', ' ORDER BY conname) INTO bad
            FROM pg_constraint c
            JOIN pg_class child ON child.oid=c.conrelid
            JOIN pg_namespace child_ns ON child_ns.oid=child.relnamespace
           WHERE c.contype='f' AND c.confrelid='public.chunks'::regclass
             AND (child_ns.nspname <> 'public' OR child.relname <> 'embeddings'
                  OR c.conname <> chunk_fk.conname
                  OR cardinality(c.conkey) <> 1 OR cardinality(c.confkey) <> 1);
          IF bad IS NOT NULL THEN
            RAISE EXCEPTION USING MESSAGE = format('MVR-05A4 unknown chunks inbound FK(s): %s', bad),
              HINT = 'Inventory the consumer before retrying.';
          END IF;
          IF (SELECT count(*) FROM pg_constraint c
               WHERE c.contype='f' AND c.confrelid='public.chunks'::regclass) <> 1 THEN
            RAISE EXCEPTION USING MESSAGE='MVR-05A4 chunks inbound FK census is not exactly one';
          END IF;
          SELECT string_agg(conname, ', ' ORDER BY conname) INTO bad
            FROM pg_constraint c
           WHERE c.contype='f' AND c.confrelid='public.membership'::regclass;
          IF bad IS NOT NULL THEN
            RAISE EXCEPTION USING MESSAGE=format('MVR-05A4 unknown membership inbound FK(s): %s', bad),
              HINT = 'Inventory and convert the consumer before rewriting membership identity.';
          END IF;

          -- A fresh lineage keeps this endpoint exactly as sets(id); the
          -- historical objects endpoint was already converted by MVR-05A3.
          SELECT c.conname INTO membership_fk FROM pg_constraint c
           WHERE c.contype='f' AND c.conrelid='public.membership'::regclass
             AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                   WHERE attrelid='public.membership'::regclass
                                     AND attname='set_id' AND NOT attisdropped)]
           LIMIT 1;
          IF membership_fk.conname IS NULL THEN
            RAISE EXCEPTION USING MESSAGE='MVR-05A4 membership.set_id FK missing';
          END IF;
          -- set_id is intentionally branch-specific: fresh membership points
          -- to sets(id); the historical post-MVR-05A3 endpoint is composite
          -- store_objects(binding, object_id).  Anything else is not guessed.
          IF membership_columns = ARRAY['id']::text[] THEN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint c
              WHERE c.conname=membership_fk.conname AND c.confrelid='public.sets'::regclass
                AND cardinality(c.conkey)=1 AND cardinality(c.confkey)=1) THEN
              RAISE EXCEPTION USING MESSAGE='MVR-05A4 unsupported fresh membership.set_id FK';
            END IF;
          ELSIF NOT EXISTS (SELECT 1 FROM pg_constraint c
              WHERE c.conname=membership_fk.conname AND c.confrelid='public.store_objects'::regclass
                AND cardinality(c.conkey)=2 AND cardinality(c.confkey)=2) THEN
            RAISE EXCEPTION USING MESSAGE='MVR-05A4 unsupported historical membership set endpoint';
          END IF;

          -- No re-attribution: MVR-05A3 must already have supplied every key.
          SELECT string_agg(table_name, ', ' ORDER BY table_name) INTO bad
            FROM (VALUES ('chunks'),('embeddings'),('relations'),('membership')) v(table_name)
           WHERE EXISTS (SELECT 1 FROM pg_attribute a
                         WHERE a.attrelid=format('public.%I', table_name)::regclass
                           AND a.attname='vault_binding_id' AND NOT a.attnotnull);
          IF bad IS NOT NULL THEN
            RAISE EXCEPTION USING MESSAGE=format('MVR-05A4 missing delivered binding invariant: %s', bad),
              HINT='Run MVR-05A3 attribution repair first; this migration never assigns bindings.';
          END IF;

          ALTER TABLE public.chunks ADD CONSTRAINT chunks_binding_id_key
            UNIQUE (vault_binding_id, id);
          EXECUTE format('ALTER TABLE public.membership DROP CONSTRAINT %I', membership_pk);
          EXECUTE format('ALTER TABLE public.membership ADD CONSTRAINT %I PRIMARY KEY (vault_binding_id, %s)',
                         membership_pk, array_to_string(membership_columns, ', '));

          update_action := CASE chunk_fk.confupdtype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
            WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END;
          delete_action := CASE chunk_fk.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
            WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END;
          match_clause := CASE chunk_fk.confmatchtype WHEN 'f' THEN ' MATCH FULL' WHEN 'p' THEN ' MATCH PARTIAL' ELSE '' END;
          deferrable_clause := CASE WHEN chunk_fk.condeferrable AND chunk_fk.condeferred THEN ' DEFERRABLE INITIALLY DEFERRED'
            WHEN chunk_fk.condeferrable THEN ' DEFERRABLE INITIALLY IMMEDIATE' ELSE ' NOT DEFERRABLE' END;
          EXECUTE format('ALTER TABLE public.embeddings DROP CONSTRAINT %I', chunk_fk.conname);
          EXECUTE format('ALTER TABLE public.embeddings ADD CONSTRAINT %I FOREIGN KEY (vault_binding_id, chunk_id) REFERENCES public.chunks (vault_binding_id, id)%s ON UPDATE %s ON DELETE %s%s',
                         chunk_fk.conname, match_clause, update_action, delete_action, deferrable_clause);
          CREATE INDEX IF NOT EXISTS embeddings_chunk_binding_idx
            ON public.embeddings (vault_binding_id, chunk_id);
          -- Retained derived views are reads too: every join carries the same
          -- binding, so a duplicate UUID in B cannot satisfy a row in A.
          CREATE OR REPLACE VIEW public.view_chunks_missing_embeddings AS
            SELECT c.vault_binding_id, c.object_id::text AS object_id,
                   count(*) AS chunk_count
              FROM public.chunks c
             WHERE NOT EXISTS (SELECT 1 FROM public.embeddings e
                WHERE e.vault_binding_id=c.vault_binding_id AND e.chunk_id=c.id)
             GROUP BY c.vault_binding_id, c.object_id;
          CREATE OR REPLACE VIEW public.view_objects_ready_for_projection AS
            SELECT d.vault_binding_id, d.object_id::text AS object_id,
                   coalesce(d.value->>'type','') AS type,
                   coalesce(d.value->>'trust','') AS trust, d.created_at
              FROM public.decisions d
             WHERE d.key='classification' AND coalesce(d.value->>'type','') <> ''
               AND NOT EXISTS (SELECT 1 FROM public.membership m
                 WHERE m.vault_binding_id=d.vault_binding_id AND m.object_id=d.object_id);
        END $mvr05a4$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("MVR-05A4 is forward-only")
