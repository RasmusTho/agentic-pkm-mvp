"""MVR-05A0 (#4543): adopt `file_state` into Alembic and rekey it by binding.

Follows the KERNEL-04 (#2766) / KERNEL-05 (#2850) precedent that moved the
`store_*` and `outbox` DDL out of imperative create-on-boot code and into the
revision chain. `file_state` was the remaining durable vault-sync table with no
migration owner: it was created at runtime by `app/db/migrations_obsidian.sql`
through `app/db/db.py::ensure_schema`, so no Alembic revision could see it and
the `integration-nightly / pg-contracts` lane (which runs `alembic upgrade
head`) never reached it.

Two things happen here, both idempotent against a database where the legacy
bootstrap SQL already created the table and already holds rows:

1. **Adoption.** The table becomes migration-owned. On a database that has no
   `file_state` it is created; on a database that has the bootstrap-created
   table it is adopted in place. No data movement, no drop-and-recreate — the
   deployed population this migration exists for keeps every row.
2. **Rekey.** The primary key moves from `path` alone to
   `(vault_binding_id, path)`. `path text PRIMARY KEY` made two vault bindings
   holding the same path mutually exclusive: binding B silently overwrote
   binding A's sync bookkeeping. That is the overwrite MVR-05A's AC-1 forbids,
   and no additive column alone reaches it because the key itself is the defect.

`vault_binding_id` is the stable registry binding id
(`app/instance/vault_registry.py::VaultRegistration.vault_binding_id`), matching
the "stable binding" namespace MVR-05A (#3859) expects for every vault-derived
projection. Existing rows are attributed to the explicit legacy compatibility
sentinel `legacy-compatibility-binding` rather than guessed onto a registry
binding: pre-MVR-05 databases are single-binding by construction, and MVR-05A's
backfill AC ("legacy rows backfill only with one provable binding; ambiguous
rows quarantine") owns the sentinel -> real-binding attribution. This slice does
not guess.

Single-vault behaviour is unchanged: with one binding value in every row,
`(vault_binding_id, path)` has exactly the uniqueness, upsert, and delete
semantics `(path)` had.

`objects.path` moves here too. It was declared in three places in the legacy
bootstrap SQL (a pre-create `ALTER ... IF EXISTS`, the `CREATE TABLE` column
list, and a post-create `ALTER`) while `objects` itself is created by Alembic
revision `202510241200` — the same split-ownership root cause. After this
revision the column has exactly one owning mechanism.

Forward-only. Measured against a migrated database, an older image behaves like
this: every `file_state` **upsert** fails loudly, because `ON CONFLICT (path)`
has no unique index on `path` alone to match and Postgres raises
`InvalidColumnReference`. Its reads and its path/uuid deletes still execute, and
they remain *correct* while only one binding exists — which is the only state an
older image can be rolled back into, since it cannot create a second binding.
So rollback stops vault-sync ingest loudly rather than silently mis-keying or
losing rows. Per `docs/RELEASE_CHANNELS/README.md :: Rollback posture` a
forward-only migration is permitted with operator acknowledgement that rollback
cannot restore DB shape.

Parity between this revision and the test-fixture create-on-demand path in
`app/db/db.py`, plus bootstrap-origin/Alembic-origin convergence and row
survival, are asserted by `tests/migrations/test_file_state_adoption.py`.

Revision ID: c7f4b1a83d29
Revises: a9f3c2d7b6e1
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "c7f4b1a83d29"
down_revision: Union[str, None] = "a9f3c2d7b6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

# Kept in sync with app/db/db.py::FILE_STATE_COMPATIBILITY_BINDING_ID by
# tests/migrations/test_file_state_adoption.py. A migration must not import
# runtime code, so the literal is duplicated and pinned by test instead.
_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Fresh create. Column order intentionally appends `vault_binding_id` last,
    # exactly where `ALTER TABLE ... ADD COLUMN` places it when this revision
    # adopts a bootstrap-created table, so both origins converge on one shape.
    # The primary key is added by the guarded block below, not here, so the
    # created and the adopted table also share one constraint name and one
    # column order inside that constraint.
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.file_state (
            path text NOT NULL,
            uuid text,
            fm_hash text,
            body_hash text,
            mtime timestamptz,
            last_seen timestamptz DEFAULT now(),
            vault_binding_id text NOT NULL DEFAULT '{_COMPATIBILITY_BINDING_ID}'
        )
        """
    )

    # Adoption of a bootstrap-created table. Every statement is a no-op on a
    # table this revision just created.
    op.execute("ALTER TABLE public.file_state ADD COLUMN IF NOT EXISTS vault_binding_id text")
    op.execute(
        f"""
        UPDATE public.file_state
           SET vault_binding_id = '{_COMPATIBILITY_BINDING_ID}'
         WHERE vault_binding_id IS NULL
        """
    )
    op.execute(
        "ALTER TABLE public.file_state "
        f"ALTER COLUMN vault_binding_id SET DEFAULT '{_COMPATIBILITY_BINDING_ID}'"
    )
    op.execute("ALTER TABLE public.file_state ALTER COLUMN vault_binding_id SET NOT NULL")
    op.execute("ALTER TABLE public.file_state ALTER COLUMN path SET NOT NULL")

    # Rekey. Guarded so re-running the revision over an already-rekeyed table
    # touches nothing: the primary key is only rewritten when its column list
    # actually differs. If a legacy table somehow holds duplicate
    # (vault_binding_id, path) pairs the ADD CONSTRAINT fails loud rather than
    # deduplicating by guess.
    op.execute(
        """
        DO $mvr05a0$
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
             WHERE con.conrelid = to_regclass('public.file_state')
               AND con.contype = 'p';

            IF current_pk IS DISTINCT FROM ARRAY['vault_binding_id', 'path']::text[] THEN
                IF current_pk_name IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE public.file_state DROP CONSTRAINT %I',
                        current_pk_name
                    );
                END IF;
                ALTER TABLE public.file_state
                    ADD CONSTRAINT file_state_pkey PRIMARY KEY (vault_binding_id, path);
            END IF;
        END
        $mvr05a0$;
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS file_state_uuid_idx ON public.file_state(uuid)")

    # `objects.path` gains its single owning mechanism here; the legacy
    # bootstrap SQL no longer declares it.
    op.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS path text")


def downgrade() -> None:
    raise RuntimeError(
        "MVR-05A0 file_state adoption is forward-only: dropping the "
        "(vault_binding_id, path) key would make two bindings holding the same "
        "path mutually exclusive again and would silently discard one of them."
    )
