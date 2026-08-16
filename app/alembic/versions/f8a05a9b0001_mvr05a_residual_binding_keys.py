"""MVR-05A residual: bind live projections and remove dead embedding schema.

The preceding scalar-compatible cutover proves every retained row belongs to
the explicit compatibility binding.  A pre-existing partial binding column is
accepted only when every row is already attributed; NULL or blank attribution
fails the transaction rather than guessing.
"""

from alembic import op


revision = "f8a05a9b0001"
down_revision = "f7a05a4b0001"
branch_labels = None
depends_on = None
reversibility = "forward-only"

_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"


def upgrade() -> None:
    op.execute(
        f"""
        DO $mvr05a_residual$
        DECLARE
          table_name text;
          binding_preexisted boolean;
          primary_key_name text;
          primary_key_columns text[];
          constraint_row record;
          fresh_membership_set_fk text;
        BEGIN
          FOREACH table_name IN ARRAY ARRAY[
            'agent_memories', 'heimdal_meeting_finalization_receipt',
            'outbox', 'sets', 'membership'
          ] LOOP
            IF to_regclass('public.' || table_name) IS NULL THEN
              RAISE EXCEPTION USING
                MESSAGE = 'MVR-05A residual migration requires public.' || table_name,
                HINT = 'Restore the supported migration lineage, then rerun alembic upgrade head.';
            END IF;
          END LOOP;

          LOCK TABLE public.agent_memories,
                     public.heimdal_meeting_finalization_receipt,
                     public.outbox,
                     public.sets,
                     public.membership
            IN SHARE ROW EXCLUSIVE MODE;

          -- agent_memories: same memory UUID may exist independently per binding.
          SELECT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid='public.agent_memories'::regclass
               AND attname='vault_binding_id' AND attnum>0 AND NOT attisdropped
          ) INTO binding_preexisted;
          IF binding_preexisted AND EXISTS (
            SELECT 1 FROM public.agent_memories
             WHERE vault_binding_id IS NULL OR btrim(vault_binding_id)=''
          ) THEN
            RAISE EXCEPTION 'partially binding-keyed agent_memories has ambiguous rows';
          END IF;
          IF NOT binding_preexisted THEN
            ALTER TABLE public.agent_memories
              ADD COLUMN vault_binding_id text NOT NULL
              DEFAULT '{_COMPATIBILITY_BINDING_ID}';
          END IF;
          ALTER TABLE public.agent_memories
            ALTER COLUMN vault_binding_id SET DEFAULT '{_COMPATIBILITY_BINDING_ID}',
            ALTER COLUMN vault_binding_id SET NOT NULL;
          SELECT c.conname, array_agg(a.attname ORDER BY k.ordinality)
            INTO primary_key_name, primary_key_columns
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
           WHERE c.conrelid='public.agent_memories'::regclass AND c.contype='p'
           GROUP BY c.conname;
          IF primary_key_columns IS DISTINCT FROM ARRAY['vault_binding_id','id']::text[] THEN
            IF primary_key_name IS NULL THEN
              RAISE EXCEPTION 'agent_memories has no primary key';
            END IF;
            EXECUTE format('ALTER TABLE public.agent_memories DROP CONSTRAINT %I', primary_key_name);
            ALTER TABLE public.agent_memories
              ADD CONSTRAINT agent_memories_pkey PRIMARY KEY (vault_binding_id, id);
          END IF;

          -- The receipt is append-only; ADD COLUMN DEFAULT classifies retained
          -- scalar rows without firing its reject-mutation trigger.
          SELECT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid='public.heimdal_meeting_finalization_receipt'::regclass
               AND attname='vault_binding_id' AND attnum>0 AND NOT attisdropped
          ) INTO binding_preexisted;
          IF binding_preexisted AND EXISTS (
            SELECT 1 FROM public.heimdal_meeting_finalization_receipt
             WHERE vault_binding_id IS NULL OR btrim(vault_binding_id)=''
          ) THEN
            RAISE EXCEPTION 'partially binding-keyed heimdal_meeting_finalization_receipt has ambiguous rows';
          END IF;
          IF NOT binding_preexisted THEN
            ALTER TABLE public.heimdal_meeting_finalization_receipt
              ADD COLUMN vault_binding_id text NOT NULL
              DEFAULT '{_COMPATIBILITY_BINDING_ID}';
          END IF;
          ALTER TABLE public.heimdal_meeting_finalization_receipt
            ALTER COLUMN vault_binding_id SET DEFAULT '{_COMPATIBILITY_BINDING_ID}',
            ALTER COLUMN vault_binding_id SET NOT NULL;
          SELECT c.conname, array_agg(a.attname ORDER BY k.ordinality)
            INTO primary_key_name, primary_key_columns
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
           WHERE c.conrelid='public.heimdal_meeting_finalization_receipt'::regclass
             AND c.contype='p'
           GROUP BY c.conname;
          IF primary_key_columns IS DISTINCT FROM
             ARRAY['vault_binding_id','session_id','state_sha256']::text[] THEN
            IF primary_key_name IS NULL THEN
              RAISE EXCEPTION 'heimdal_meeting_finalization_receipt has no primary key';
            END IF;
            EXECUTE format(
              'ALTER TABLE public.heimdal_meeting_finalization_receipt DROP CONSTRAINT %I',
              primary_key_name
            );
            ALTER TABLE public.heimdal_meeting_finalization_receipt
              ADD CONSTRAINT heimdal_meeting_finalization_receipt_pkey
              PRIMARY KEY (vault_binding_id, session_id, state_sha256);
          END IF;

          -- Fresh membership points at sets; retained historical membership
          -- points at store_objects and must remain on that proven endpoint.
          SELECT c.conname INTO fresh_membership_set_fk
            FROM pg_constraint c
           WHERE c.conrelid='public.membership'::regclass AND c.contype='f'
             AND c.confrelid='public.sets'::regclass;
          IF (SELECT count(*) FROM pg_constraint c
               WHERE c.conrelid='public.membership'::regclass AND c.contype='f'
                 AND c.confrelid='public.sets'::regclass) > 1 THEN
            RAISE EXCEPTION 'membership has multiple foreign keys to sets';
          END IF;
          IF EXISTS (
            SELECT 1 FROM pg_constraint c
             WHERE c.contype='f' AND c.confrelid='public.sets'::regclass
               AND c.conrelid<>'public.membership'::regclass
          ) THEN
            RAISE EXCEPTION 'sets has an unsupported inbound foreign-key consumer';
          END IF;
          IF fresh_membership_set_fk IS NOT NULL THEN
            EXECUTE format(
              'ALTER TABLE public.membership DROP CONSTRAINT %I',
              fresh_membership_set_fk
            );
          END IF;

          SELECT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid='public.sets'::regclass
               AND attname='vault_binding_id' AND attnum>0 AND NOT attisdropped
          ) INTO binding_preexisted;
          IF binding_preexisted AND EXISTS (
            SELECT 1 FROM public.sets
             WHERE vault_binding_id IS NULL OR btrim(vault_binding_id)=''
          ) THEN
            RAISE EXCEPTION 'partially binding-keyed sets has ambiguous rows';
          END IF;
          IF NOT binding_preexisted THEN
            ALTER TABLE public.sets
              ADD COLUMN vault_binding_id text NOT NULL
              DEFAULT '{_COMPATIBILITY_BINDING_ID}';
          END IF;
          ALTER TABLE public.sets
            ALTER COLUMN vault_binding_id SET DEFAULT '{_COMPATIBILITY_BINDING_ID}',
            ALTER COLUMN vault_binding_id SET NOT NULL;
          SELECT c.conname, array_agg(a.attname ORDER BY k.ordinality)
            INTO primary_key_name, primary_key_columns
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
           WHERE c.conrelid='public.sets'::regclass AND c.contype='p'
           GROUP BY c.conname;
          IF primary_key_columns IS DISTINCT FROM ARRAY['vault_binding_id','id']::text[] THEN
            IF primary_key_name IS NULL THEN
              RAISE EXCEPTION 'sets has no primary key';
            END IF;
            EXECUTE format('ALTER TABLE public.sets DROP CONSTRAINT %I', primary_key_name);
            ALTER TABLE public.sets
              ADD CONSTRAINT sets_pkey PRIMARY KEY (vault_binding_id, id);
          END IF;
          FOR constraint_row IN
            SELECT c.conname
              FROM pg_constraint c
             WHERE c.conrelid='public.sets'::regclass AND c.contype='u'
               AND (SELECT array_agg(a.attname ORDER BY k.ordinality)
                      FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality)
                      JOIN pg_attribute a
                        ON a.attrelid=c.conrelid AND a.attnum=k.attnum)
                   = ARRAY['name']::text[]
          LOOP
            EXECUTE format('ALTER TABLE public.sets DROP CONSTRAINT %I', constraint_row.conname);
          END LOOP;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
             WHERE c.conrelid='public.sets'::regclass AND c.contype='u'
               AND (SELECT array_agg(a.attname ORDER BY k.ordinality)
                      FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality)
                      JOIN pg_attribute a
                        ON a.attrelid=c.conrelid AND a.attnum=k.attnum)
                   = ARRAY['vault_binding_id','name']::text[]
          ) THEN
            ALTER TABLE public.sets
              ADD CONSTRAINT sets_binding_name_key UNIQUE (vault_binding_id, name);
          END IF;
          IF fresh_membership_set_fk IS NOT NULL THEN
            ALTER TABLE public.membership
              ADD CONSTRAINT membership_set_binding_fkey
              FOREIGN KEY (vault_binding_id, set_id)
              REFERENCES public.sets (vault_binding_id, id) ON DELETE CASCADE;
          END IF;

          -- MVR-05A7 already owns the outbox schema.  This residual only
          -- verifies that delivered shape rather than duplicating its migration.
          IF NOT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid='public.outbox'::regclass
               AND attname='vault_binding_id' AND attnotnull
               AND attnum>0 AND NOT attisdropped
          ) OR NOT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid='public.outbox'::regclass
               AND attname='legacy_key'
               AND attnum>0 AND NOT attisdropped
          ) OR EXISTS (
            SELECT 1 FROM public.outbox
             WHERE vault_binding_id IS NULL OR btrim(vault_binding_id)=''
                OR legacy_key IS NULL
          ) THEN
            RAISE EXCEPTION USING
              MESSAGE = 'MVR-05A residual migration requires the delivered MVR-05A7 outbox shape',
              HINT = 'Run the complete migration lineage through f6a05a7b0001 first.';
          END IF;

          -- Historical bootstrap embeddings have no producer or reader under
          -- app/**.  Removing the dead derived table is safer than inventing a
          -- second runtime projection path.
          DROP TABLE IF EXISTS public.objects_embeddings;
        END $mvr05a_residual$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "MVR-05A residual binding keys are forward-only: restoring global keys "
        "would make equal artifacts from two bindings mutually exclusive."
    )
