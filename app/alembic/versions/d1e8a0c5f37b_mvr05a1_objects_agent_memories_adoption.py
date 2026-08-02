"""MVR-05A1 (#4560): adopt `objects` and `agent_memories`, rekey `objects` by binding.

This revision is the second half of the fix MVR-05A0 (#4543) started on
`file_state`, and it ends the defect class rather than clearing one more table.

`app/db/migrations_obsidian.sql` was executed by `app/db/db.py::ensure_schema`
on the first `conn_rw()` of **every process**. Two of its statements made the
revision chain unable to own `objects` at all:

    ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;
    ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);

Any binding-keyed primary key a migration installed on `objects` was dropped and
replaced with `PRIMARY KEY (id)` at the next process boot. On a single-binding
instance no two rows share an id, so the re-add **succeeded with no error**: the
migration was reverted silently, and only then did a second binding's rows begin
overwriting the first's. A third statement,

    CREATE UNIQUE INDEX IF NOT EXISTS objects_uuid_idx ON public.objects(uuid);

made "two bindings containing the same artifact UUID" a direct unique violation
on every database whose `objects` table was created by that bootstrap before
Alembic ever ran.

Superseding those statements was not enough while the file still executed, so
this slice retires the runtime DDL path with the same change. See
`tests/architecture/test_durable_table_ownership.py`.

Two tables are adopted:

1. **`objects`** had split ownership: created by revisions `fe9a3607841f` and
   `202510241200`, then re-shaped on every boot by the bootstrap SQL, which
   supplied `source_ref`, the legacy `uuid`->`id` backfill, the primary-key
   rewrite, `objects_created_at_idx` and `objects_source_ref_idx`. All of that
   moves here, and the primary key becomes `(vault_binding_id, id)` while
   `objects_uuid_idx` becomes `UNIQUE (vault_binding_id, uuid)`.

   `objects.id` is not an independent surrogate in practice: the vault-sync
   producer writes `id = uuid = ` the note's artifact UUID
   (`app/services/vault_sync.py`), and the legacy backfill below sets
   `id = uuid` for rows that predate the column. So `PRIMARY KEY (id)` is
   exactly the "one row per artifact UUID across every binding" constraint
   MVR-05A's AC-1 forbids, and no additive column reaches it — the key itself is
   the defect, the same shape of finding as `file_state`'s `path` key.

2. **`agent_memories`** was bootstrap-only, with zero references anywhere in the
   revision chain — the same condition `file_state` was in before #4543. It is
   adopted verbatim: same columns, same primary key, same index. No shape
   change, so a deployed table is adopted in place and keeps every row.

`vault_binding_id` reuses MVR-05A0's namespace and its explicit
`legacy-compatibility-binding` sentinel rather than introducing a second
binding-identity scheme. Real binding attribution for legacy rows remains
MVR-05A (#3859)'s backfill AC ("legacy rows backfill only with one provable
binding; ambiguous rows quarantine"); this slice does not guess.

Single-vault behaviour is unchanged: with one binding value in every row,
`(vault_binding_id, id)` has exactly the uniqueness and lookup semantics `(id)`
had, and `UNIQUE (vault_binding_id, uuid)` exactly the semantics `UNIQUE (uuid)`
had.

Every statement is idempotent against a database the bootstrap already created
and populated. Adoption is in place: no drop-and-recreate, no data movement.

Two preflights fail loudly rather than damaging live data:

- an inbound foreign key still referencing `objects` would make the primary-key
  rewrite impossible; #3510 (`7e4f2a1c9d30`) already moved every known consumer
  to `store_objects`, so this raises with that hint instead of surfacing an
  opaque dependent-objects error mid-upgrade;
- duplicate `(vault_binding_id, uuid)` rows would make the unique index
  impossible. `objects_uuid_idx` is non-unique on any database where Alembic
  created `objects` first, so duplicates are physically possible there even
  though `app/objects/identity.py` already refuses to resolve them
  ("reconcile duplicate objects.uuid rows"). This raises with a reconcile hint
  rather than deduplicating by guess.

Forward-only, and both rollback outcomes were measured rather than reasoned:

- On a **single-binding** database an older image starts, and its startup
  bootstrap drops `objects_pkey` and re-adds `PRIMARY KEY (id)`, silently
  restoring the single-binding key. Every row survives.
- On a database that already holds **two bindings for one artifact UUID** the
  older image cannot start at all: `conn_rw()` raises
  `UniqueViolation: could not create unique index "objects_pkey"`, and because
  the whole bootstrap runs in one transaction the schema is left untouched.

In both cases `objects_uuid_idx` stays binding-scoped, because
`CREATE UNIQUE INDEX IF NOT EXISTS` matches on name and never restores a
`(uuid)`-only unique index. That has a consequence worth stating plainly: the
older image's third `objects` upsert fallback, `on conflict (uuid)`, then has no
matching unique index and raises `InvalidColumnReference` — measured. Its
primary `on conflict (id)` path works again once the bootstrap has restored the
old key, so vault-sync ingest continues; only that fallback is dead.

So a rollback must be followed by re-running `alembic upgrade head` against a
post-#4560 image before a second binding is created. Per
`docs/RELEASE_CHANNELS/README.md :: Rollback posture` a forward-only migration is
permitted with operator acknowledgement that rollback cannot restore DB shape.

Adoption, row survival, the restart case, the two-binding case, and
bootstrap-origin/Alembic-origin convergence are asserted by
`tests/migrations/test_objects_adoption.py`; single-vault equivalence and
first-boot on a fresh database by
`tests/integration/test_single_vault_compatibility.py`.

Revision ID: d1e8a0c5f37b
Revises: c7f4b1a83d29
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "d1e8a0c5f37b"
down_revision: Union[str, None] = "c7f4b1a83d29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

# The same sentinel MVR-05A0 (#4543) introduced, not a second scheme. Kept in
# sync with app/db/db.py::COMPATIBILITY_BINDING_ID by
# tests/migrations/test_objects_adoption.py. A migration must not import runtime
# code, so the literal is duplicated and pinned by test instead.
_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ #
    # objects
    # ------------------------------------------------------------------ #

    # Fresh create. Unreachable from the revision chain itself — `fe9a3607841f`
    # always creates `objects` first — but the test-fixture autocreate path in
    # `app/db/db.py` starts from nothing, and its shape parity with this
    # statement is what keeps it from becoming a second source of truth.
    #
    # Column order, types and nullability deliberately reproduce what the
    # deployed lineage actually holds rather than what would be chosen today:
    # `payload` is `json` (from `fe9a3607841f`'s `sa.JSON()`) with a `::jsonb`
    # default, `id` carries no server default, and `vault_binding_id` is
    # appended last, exactly where `ALTER TABLE ... ADD COLUMN` places it when
    # this revision adopts an existing table. Both origins therefore converge on
    # one shape.
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.objects (
            id uuid NOT NULL,
            uuid uuid,
            kind text NOT NULL,
            payload json NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            path text,
            source_ref text,
            vault_binding_id text NOT NULL DEFAULT '{_COMPATIBILITY_BINDING_ID}'
        )
        """
    )

    # Adoption of an existing table. Every statement is a no-op on a table this
    # revision just created. `path` is deliberately absent: MVR-05A0
    # (`c7f4b1a83d29`) owns that column and must stay its only owner.
    op.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS id uuid")
    op.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS uuid uuid")
    op.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS source_ref text")
    op.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS vault_binding_id text")

    # Legacy identifier backfill, moved verbatim from the retired bootstrap SQL.
    # Pre-v5 databases used `uuid` as the only identifier.
    op.execute("UPDATE public.objects SET id = uuid WHERE id IS NULL AND uuid IS NOT NULL")
    op.execute("UPDATE public.objects SET id = gen_random_uuid() WHERE id IS NULL")
    op.execute("UPDATE public.objects SET uuid = id WHERE uuid IS NULL")

    op.execute(
        f"""
        UPDATE public.objects
           SET vault_binding_id = '{_COMPATIBILITY_BINDING_ID}'
         WHERE vault_binding_id IS NULL
        """
    )
    op.execute(
        "ALTER TABLE public.objects "
        f"ALTER COLUMN vault_binding_id SET DEFAULT '{_COMPATIBILITY_BINDING_ID}'"
    )
    op.execute("ALTER TABLE public.objects ALTER COLUMN vault_binding_id SET NOT NULL")
    op.execute("ALTER TABLE public.objects ALTER COLUMN id SET NOT NULL")

    # Preflight: an inbound FK on `objects` makes the primary-key rewrite
    # impossible. #3510 (7e4f2a1c9d30) moved every reviewed consumer to
    # `store_objects`, so on the supported lineage this finds nothing. Raise with
    # the hint rather than letting `DROP CONSTRAINT` fail opaquely part-way
    # through the upgrade.
    op.execute(
        """
        DO $mvr05a1_fk$
        DECLARE
            blocking text;
        BEGIN
            SELECT string_agg(
                       format('%s.%s', con.conrelid::regclass::text, con.conname),
                       ', ' ORDER BY con.conname
                   )
              INTO blocking
              FROM pg_constraint con
             WHERE con.confrelid = to_regclass('public.objects')
               AND con.contype = 'f';

            IF blocking IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format(
                        'MVR-05A1 (#4560) cannot rekey public.objects: inbound foreign '
                        'key(s) still reference it (%s)', blocking
                    ),
                    HINT = 'Alembic revision 7e4f2a1c9d30 (#3510) moves legacy objects '
                           'FK consumers to store_objects. Complete that cutover, then '
                           'rerun alembic upgrade head.';
            END IF;
        END
        $mvr05a1_fk$;
        """
    )

    # Rekey. Guarded so re-running the revision over an already-rekeyed table
    # touches nothing: the primary key is only rewritten when its column list
    # actually differs, which is what keeps the constraint oid stable and proves
    # the guard rather than an unconditional drop-and-re-add.
    op.execute(
        """
        DO $mvr05a1_pk$
        DECLARE
            current_pk text[];
            current_pk_name text;
        BEGIN
            SELECT array_agg(att.attname ORDER BY key.ordinality), max(con.conname)
              INTO current_pk, current_pk_name
              FROM pg_constraint con
              JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality)
                ON true
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid
               AND att.attnum = key.attnum
             WHERE con.conrelid = to_regclass('public.objects')
               AND con.contype = 'p';

            IF current_pk IS DISTINCT FROM ARRAY['vault_binding_id', 'id']::text[] THEN
                IF current_pk_name IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE public.objects DROP CONSTRAINT %I',
                        current_pk_name
                    );
                END IF;
                ALTER TABLE public.objects
                    ADD CONSTRAINT objects_pkey PRIMARY KEY (vault_binding_id, id);
            END IF;
        END
        $mvr05a1_pk$;
        """
    )

    # Rekey `objects_uuid_idx`. On a database whose `objects` was created by the
    # bootstrap SQL this index is `UNIQUE (uuid)` — a global uniqueness that
    # makes two bindings holding the same artifact UUID a direct violation. On a
    # database where Alembic created the table first it is the *non-unique*
    # `fe9a3607841f` index of the same name, because `CREATE UNIQUE INDEX IF NOT
    # EXISTS` matches on name and silently no-ops. Both converge here on
    # `UNIQUE (vault_binding_id, uuid)`.
    op.execute(
        """
        DO $mvr05a1_uuid_idx$
        DECLARE
            duplicates text;
            current_columns text[];
            current_unique boolean;
        BEGIN
            -- `indkey` is an int2vector; cast before unnest so this does not
            -- depend on the implicit vector->array coercion. `indnkeyatts`,
            -- not `indnatts`: the latter counts INCLUDEd columns, which do not
            -- participate in uniqueness.
            SELECT array_agg(att.attname ORDER BY key.ordinality), bool_and(idx.indisunique)
              INTO current_columns, current_unique
              FROM pg_index idx
              JOIN LATERAL unnest(idx.indkey::int2[]) WITH ORDINALITY key(attnum, ordinality)
                ON key.ordinality <= idx.indnkeyatts
              JOIN pg_attribute att
                ON att.attrelid = idx.indrelid
               AND att.attnum = key.attnum
             WHERE idx.indrelid = to_regclass('public.objects')
               AND idx.indexrelid = to_regclass('public.objects_uuid_idx');

            IF current_columns IS NOT DISTINCT FROM ARRAY['vault_binding_id', 'uuid']::text[]
               AND current_unique THEN
                RETURN;
            END IF;

            SELECT string_agg(format('(%s, %s)', vault_binding_id, uuid), ', ')
              INTO duplicates
              FROM (
                    SELECT vault_binding_id, uuid
                      FROM public.objects
                     WHERE uuid IS NOT NULL
                     GROUP BY vault_binding_id, uuid
                    HAVING count(*) > 1
                     LIMIT 10
                   ) duplicate_rows;

            IF duplicates IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format(
                        'MVR-05A1 (#4560) cannot make objects_uuid_idx unique per binding: '
                        'duplicate (vault_binding_id, uuid) rows exist (%s)', duplicates
                    ),
                    HINT = 'app/objects/identity.py already refuses to resolve a duplicated '
                           'objects.uuid. Reconcile the duplicate rows, then rerun '
                           'alembic upgrade head. This migration does not deduplicate by guess.';
            END IF;

            IF to_regclass('public.objects_uuid_idx') IS NOT NULL THEN
                DROP INDEX public.objects_uuid_idx;
            END IF;
            CREATE UNIQUE INDEX objects_uuid_idx
                ON public.objects (vault_binding_id, uuid);
        END
        $mvr05a1_uuid_idx$;
        """
    )

    # A unique index on `uuid` **or** `id` alone, under any name, re-imposes
    # exactly the global uniqueness the rekey removes — behind a key that looks
    # correct. Both columns matter and for the same reason: `id` is the second
    # primary-key column, the structural analogue of `file_state`'s `path`, and
    # the vault-sync producer writes `id = uuid`, so one unique row per `id` is
    # one row per artifact UUID across every binding.
    #
    # `app/db/sql/objects_uuid_unrestrict.sql` created `objects_uuid_unique_idx`
    # and was deleted by this slice, but deleting the file cannot remove the
    # index from a database where it was ever run, and the retired bootstrap's
    # `objects_pkey PRIMARY KEY (id)` is only reached by the rekey above when it
    # is still the primary key rather than a bare unique index.
    #
    # This mirrors the leftover `path`-only check
    # `app/db/db.py::assert_file_state_schema` performs for `file_state`, and
    # runs after the rekey above so it cannot match the binding-scoped index it
    # just created. A constraint-backed index needs
    # `ALTER TABLE ... DROP CONSTRAINT`, so the hint names both spellings.
    op.execute(
        """
        DO $mvr05a1_stray_idx$
        DECLARE
            stray text;
        BEGIN
            SELECT string_agg(
                       format('%s (unique on %s)', cls.relname, stray_column),
                       ', ' ORDER BY cls.relname
                   )
              INTO stray
              FROM (
                    SELECT idx.indexrelid,
                           (
                             SELECT att.attname
                               FROM pg_attribute att
                              WHERE att.attrelid = idx.indrelid
                                AND att.attnum = idx.indkey[0]
                           ) AS stray_column
                      FROM pg_index idx
                     WHERE idx.indrelid = to_regclass('public.objects')
                       AND idx.indisunique
                       -- indnkeyatts, not indnatts: the latter counts INCLUDEd
                       -- columns, which do not participate in uniqueness.
                       AND idx.indnkeyatts = 1
                   ) single_column
              JOIN pg_class cls ON cls.oid = single_column.indexrelid
             WHERE single_column.stray_column IN ('uuid', 'id');

            IF stray IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format(
                        'MVR-05A1 (#4560): public.objects carries single-column unique '
                        'index(es) %s. Either re-imposes one-row-per-artifact-UUID across '
                        'every binding, behind the (vault_binding_id, ...) key', stray
                    ),
                    HINT = 'Drop it with DROP INDEX, or ALTER TABLE public.objects DROP '
                           'CONSTRAINT if it backs a constraint, then rerun alembic '
                           'upgrade head. It is the exact constraint MVR-05A AC-1 forbids.';
            END IF;
        END
        $mvr05a1_stray_idx$;
        """
    )

    # The two remaining `objects` indexes the bootstrap SQL owned.
    op.execute(
        "CREATE INDEX IF NOT EXISTS objects_created_at_idx "
        "ON public.objects (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS objects_source_ref_idx ON public.objects (source_ref)"
    )

    # ------------------------------------------------------------------ #
    # agent_memories
    # ------------------------------------------------------------------ #

    # Pure adoption, verbatim from the retired bootstrap SQL. No shape change, so
    # a deployed table is adopted in place by `IF NOT EXISTS` and keeps every
    # row. Its sole consumer is `app/memory_kv/store.py`.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.agent_memories (
            id uuid PRIMARY KEY,
            run_id uuid NULL,
            layer text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS agent_memories_created_at_idx "
        "ON public.agent_memories (created_at DESC)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "MVR-05A1 objects/agent_memories adoption is forward-only: restoring "
        "PRIMARY KEY (id) and a globally unique objects_uuid_idx would make two "
        "vault bindings holding the same artifact UUID mutually exclusive again, "
        "and would silently discard one of them."
    )
