from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

from app.config.database import resolve_runtime_database_url
from app.db.dsn import connect as _connect, resolve_dsn
from app.settings import settings
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID

_SCHEMA_INITIALIZED = False

# MVR-05A0 (#4543) / MVR-05A1 (#4560): the stable binding id every legacy
# `file_state` and `objects` row is attributed to until MVR-05A (#3859) ships the
# compatibility ingress translator that derives the real authorized
# `vault_binding_id`
# (``app/instance/vault_registry.py::VaultRegistration.vault_binding_id``).
#
# It is deliberately an explicit sentinel and not a registry-shaped
# ``binding-<uuid4>`` value: a pre-MVR-05 database is single-binding by
# construction, so attributing its rows to one named legacy binding is provable
# rather than a guess, and MVR-05A's backfill can tell "not yet attributed"
# from "attributed to binding X" without inspecting the registry.
#
# One namespace, one literal, for every table that gains a binding key. Defined
# in the storage-neutral ``app.instance.binding_ids`` module and kept in sync with
# Alembic revisions ``c7f4b1a83d29`` and ``d1e8a0c5f37b`` by
# ``tests/migrations/test_file_state_adoption.py`` and
# ``tests/migrations/test_objects_adoption.py``.
# Retained name from #4543 so existing importers keep working; it is the same
# sentinel, not a second scheme.
FILE_STATE_COMPATIBILITY_BINDING_ID = COMPATIBILITY_BINDING_ID

# Test-fixture create-on-demand for the migration-owned durable tables,
# mirroring the KERNEL-04 (#2766) / KERNEL-05 (#2850) contract for `store_*` and
# `outbox`. Production DDL authority is the Alembic revision chain
# (`c7f4b1a83d29` for `file_state`, `d1e8a0c5f37b` for `objects` and
# `agent_memories`); scratch databases opt in through STORE_SCHEMA_AUTOCREATE=1
# (tests/conftest.py). Shape parity with those revisions is asserted by
# tests/migrations/test_file_state_adoption.py and
# tests/migrations/test_objects_adoption.py.
#
# This is the *only* DDL this module issues, and it is inert outside tests.
# Since MVR-05A1 (#4560) there is no runtime bootstrap SQL: a legacy
# `migrations_obsidian.sql` used to run here on the first `conn_rw()` of every
# process and silently reverted any binding-keyed `objects` primary key an
# Alembic revision had installed.
# Grouped by table so a group can be skipped whole. `CREATE TABLE IF NOT EXISTS`
# silently no-ops on a database that already holds the table in an older shape,
# and the statements after it then reference columns that do not exist there —
# so "the table is absent" is the only condition under which this fixture may
# declare anything at all. A database that already has the table is owned by
# whichever revision created it, and the fixture must not reshape it. That is
# the same ownership rule the slice enforces everywhere else.
_MIGRATION_OWNED_AUTOCREATE_SQL: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "public.standing_questions",
        (
            """
            CREATE TABLE public.standing_questions (
                vault_binding_id text NOT NULL,
                question_id text NOT NULL,
                scope text NOT NULL,
                text text NOT NULL,
                status text NOT NULL CHECK (status IN ('open', 'answered', 'closed')),
                created_at timestamptz NOT NULL,
                registered_via text NOT NULL CHECK (registered_via IN ('capture_intent', 'explicit')),
                standing_answer_ref text,
                candidate_answer_ref text,
                evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
                last_matched_at timestamptz,
                last_refreshed_at timestamptz,
                source_path text NOT NULL,
                PRIMARY KEY (vault_binding_id, question_id),
                UNIQUE (vault_binding_id, source_path)
            )
            """,
            "CREATE INDEX standing_questions_binding_status_idx "
            "ON public.standing_questions (vault_binding_id, status)",
            "CREATE INDEX standing_questions_scope_idx ON public.standing_questions (scope)",
        ),
    ),
    (
        "public.episodes",
        (
            """
            CREATE TABLE public.episodes (
                vault_binding_id text NOT NULL,
                episode_id text NOT NULL,
                scope text NOT NULL,
                title text NOT NULL,
                time_start timestamptz NOT NULL,
                time_end timestamptz,
                closed boolean NOT NULL DEFAULT false,
                segmentation text NOT NULL,
                parent_episode text,
                space jsonb NOT NULL DEFAULT '[]'::jsonb,
                protagonists jsonb NOT NULL DEFAULT '[]'::jsonb,
                goal jsonb NOT NULL DEFAULT '[]'::jsonb,
                causation jsonb NOT NULL DEFAULT '[]'::jsonb,
                derived_from jsonb NOT NULL DEFAULT '[]'::jsonb,
                note_path text NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (vault_binding_id, episode_id),
                CONSTRAINT episodes_id_shape_chk CHECK (
                    episode_id ~ '^ep-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                ),
                CONSTRAINT episodes_segmentation_chk
                    CHECK (segmentation IN ('proposed', 'accepted', 're-cut'))
            )
            """,
            "CREATE INDEX episodes_binding_scope_idx ON public.episodes (vault_binding_id, scope)",
            "CREATE INDEX episodes_time_start_idx ON public.episodes (time_start)",
            "CREATE INDEX episodes_closed_idx ON public.episodes (closed)",
            "CREATE INDEX episodes_parent_episode_idx ON public.episodes (parent_episode)",
        ),
    ),
    (
        "public.episode_engine_state",
        (
            """
            CREATE TABLE public.episode_engine_state (
                vault_binding_id text NOT NULL,
                key text NOT NULL,
                value jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (vault_binding_id, key)
            )
            """,
        ),
    ),
    (
        "public.episode_artifact_binding",
        (
            """
            CREATE TABLE public.episode_artifact_binding (
                vault_binding_id text NOT NULL,
                artifact_ref text NOT NULL,
                episode_id text NOT NULL,
                scope text NOT NULL,
                basis text NOT NULL,
                confidence double precision NOT NULL,
                binding_state text NOT NULL DEFAULT 'active',
                rule text NOT NULL,
                assigned_at timestamptz NOT NULL DEFAULT now(),
                corrected_at timestamptz,
                PRIMARY KEY (vault_binding_id, artifact_ref, episode_id),
                CONSTRAINT episode_artifact_binding_basis_chk
                    CHECK (basis IN ('provenance', 'time_overlap')),
                CONSTRAINT episode_artifact_binding_state_chk
                    CHECK (binding_state IN ('active', 'corrected'))
            )
            """,
            "CREATE INDEX episode_artifact_binding_binding_episode_idx "
            "ON public.episode_artifact_binding (vault_binding_id, episode_id)",
            "CREATE INDEX episode_artifact_binding_scope_idx "
            "ON public.episode_artifact_binding (scope)",
            "CREATE INDEX episode_artifact_binding_state_idx "
            "ON public.episode_artifact_binding (binding_state)",
        ),
    ),
    (
        "public.decision_outcomes",
        (
            """
            CREATE TABLE public.decision_outcomes (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                vault_binding_id text NOT NULL,
                decision_object_id uuid NOT NULL,
                decision_uuid uuid NOT NULL,
                rung_index integer NOT NULL CHECK (rung_index >= 0),
                outcome text NOT NULL CHECK (
                    outcome IN ('held', 'partly_held', 'did_not_hold', 'unknown_yet')
                ),
                note text,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (vault_binding_id, decision_uuid, rung_index)
            )
            """,
            "CREATE INDEX decision_outcomes_binding_object_idx "
            "ON public.decision_outcomes (vault_binding_id, decision_object_id)",
        ),
    ),
    (
        "public.file_state",
        (
            f"""
            CREATE TABLE public.file_state (
                path text NOT NULL,
                uuid text,
                fm_hash text,
                body_hash text,
                mtime timestamptz,
                last_seen timestamptz DEFAULT now(),
                vault_binding_id text NOT NULL DEFAULT '{COMPATIBILITY_BINDING_ID}',
                CONSTRAINT file_state_pkey PRIMARY KEY (vault_binding_id, path)
            )
            """,
            "CREATE INDEX file_state_uuid_idx ON public.file_state(uuid)",
        ),
    ),
    (
        # The watcher continuity mirror. Column order, types and nullability
        # reproduce Alembic revision `d1e8a0c5f37b` exactly, including
        # `payload json` (the deployed lineage's `sa.JSON()` type) and `id`
        # without a server default.
        "public.objects",
        (
            f"""
            CREATE TABLE public.objects (
                id uuid NOT NULL,
                uuid uuid,
                kind text NOT NULL,
                payload json NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now(),
                path text,
                source_ref text,
                vault_binding_id text NOT NULL DEFAULT '{COMPATIBILITY_BINDING_ID}',
                CONSTRAINT objects_pkey PRIMARY KEY (vault_binding_id, id)
            )
            """,
            "CREATE UNIQUE INDEX objects_uuid_idx ON public.objects (vault_binding_id, uuid)",
            "CREATE INDEX objects_created_at_idx ON public.objects (created_at DESC)",
            "CREATE INDEX objects_source_ref_idx ON public.objects (source_ref)",
            # Owned in production by revisions `fe9a3607841f` and `202510241200`
            # respectively. Reproduced here only so a scratch database that never
            # ran Alembic reaches the same shape; parity is what stops this
            # fixture becoming a second source of truth.
            "CREATE INDEX objects_kind_idx ON public.objects (kind)",
            "CREATE INDEX ix_objects_payload "
            "ON public.objects USING GIN ((payload::jsonb) jsonb_path_ops)",
        ),
    ),
    (
        "public.agent_memories",
        (
            f"""
            CREATE TABLE public.agent_memories (
                id uuid NOT NULL,
                run_id uuid NULL,
                layer text NOT NULL,
                payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                provenance jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                vault_binding_id text NOT NULL DEFAULT '{COMPATIBILITY_BINDING_ID}',
                PRIMARY KEY (vault_binding_id, id)
            )
            """,
            "CREATE INDEX agent_memories_created_at_idx "
            "ON public.agent_memories (created_at DESC)",
        ),
    ),
)


def _schema_autocreate_enabled() -> bool:
    """Whether test fixtures opted into create-on-demand schema (KERNEL-04)."""
    return (os.getenv("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


class FileStateSchemaMissingError(RuntimeError):
    """Raised when the migration-owned `file_state` schema is absent or stale."""


def assert_file_state_schema(conn: psycopg.Connection) -> None:
    """Fail loudly when the database predates Alembic revision `c7f4b1a83d29`.

    The `Invariant -> producers` rule in `AGENTS.md :: Required rules` pairs a
    runtime precondition with a fail-loud preflight, matching what KERNEL-04
    (#2766) and KERNEL-05 (#2850) do for `store_*` and `outbox`. Without it a
    stale database returns cleanly from `ensure_schema`, `conn_rw` latches
    `_SCHEMA_INITIALIZED`, and the operator learns about it only when the first
    vault-sync write raises an opaque invalid-conflict-target error part-way
    through a watcher tick.

    `ensure_schema` deliberately does not gate on this in production. That
    function is a shared seam — `app/services/outbox.py::bootstrap` calls it too
    — and the `file_state` key is no concern of the outbox path; gating there
    would mask `OutboxSchemaMissingError`. The production caller is the
    vault-sync seam in `app/services/vault_sync.py`, the sole consumer of the
    table. (Under `STORE_SCHEMA_AUTOCREATE=1` the test-fixture autocreate calls
    this too, after creating the table, so a scratch database that already holds
    the legacy shape gets the same hint instead of an unexplained
    `UndefinedColumn`. That path is inert in production.)

    Checks the three things the rekey depends on: that the table exists, that its
    primary key is `(vault_binding_id, path)`, and that no unique index on `path`
    alone survives to re-impose one-binding-per-path behind that key.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              to_regclass('public.file_state') IS NOT NULL AS table_exists,
              COALESCE((
                SELECT array_agg(att.attname ORDER BY key.ordinality)
                  FROM pg_constraint con
                  JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality)
                    ON true
                  JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = key.attnum
                 WHERE con.conrelid = to_regclass('public.file_state')
                   AND con.contype = 'p'
              ), ARRAY[]::text[]) AS primary_key,
              COALESCE((
                SELECT array_agg(cls.relname)
                  FROM pg_index idx
                  JOIN pg_class cls ON cls.oid = idx.indexrelid
                 WHERE idx.indrelid = to_regclass('public.file_state')
                   AND idx.indisunique
                   -- indnkeyatts, not indnatts: the latter counts INCLUDEd
                   -- columns, so `UNIQUE(path) INCLUDE (uuid)` would slip past
                   -- while still re-imposing one-binding-per-path.
                   AND idx.indnkeyatts = 1
                   AND (
                     SELECT att.attname
                       FROM pg_attribute att
                      WHERE att.attrelid = idx.indrelid
                        AND att.attnum = idx.indkey[0]
                   ) = 'path'
              ), ARRAY[]::text[]) AS path_only_unique
            """
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        table_exists = row["table_exists"]
        primary_key = row["primary_key"]
        path_only_unique = row["path_only_unique"]
    else:
        table_exists, primary_key, path_only_unique = (
            (row[0], row[1], row[2]) if row else (False, [], [])
        )

    if not table_exists:
        raise FileStateSchemaMissingError(
            "public.file_state is missing. It is owned by Alembic revision "
            "c7f4b1a83d29 (MVR-05A0, #4543), not by the runtime bootstrap SQL. "
            "Run `alembic upgrade head` (scripts/run_migrations.sh) before "
            "starting a vault-sync producer."
        )
    if list(primary_key or []) != ["vault_binding_id", "path"]:
        raise FileStateSchemaMissingError(
            "public.file_state has primary key "
            f"{list(primary_key or [])!r}, expected ['vault_binding_id', 'path']. "
            "This database predates Alembic revision c7f4b1a83d29 (MVR-05A0, "
            "#4543); run `alembic upgrade head` (scripts/run_migrations.sh) "
            "before starting a vault-sync producer."
        )
    if path_only_unique:
        raise FileStateSchemaMissingError(
            f"public.file_state carries unique index(es) {list(path_only_unique)!r} "
            "on `path` alone. That re-imposes one-binding-per-path behind the "
            "(vault_binding_id, path) key, which is exactly the overwrite "
            "MVR-05A0 (#4543) removed. Drop the index before starting a "
            "vault-sync producer."
        )


class ObjectsSchemaMissingError(RuntimeError):
    """Raised when the migration-owned `objects` schema is absent or stale."""


def assert_objects_schema(conn: psycopg.Connection) -> None:
    """Fail loudly when the database predates Alembic revision `d1e8a0c5f37b`.

    The counterpart to `assert_file_state_schema`, and it exists for the same
    reason the `AGENTS.md :: Required rules` `Invariant -> producers` rule gives:
    pair a runtime precondition with a fail-loud preflight.

    Before MVR-05A1 (#4560) a database whose `objects` still had
    `PRIMARY KEY (id)` worked, because the runtime bootstrap reshaped the table
    on every process boot. That bootstrap is gone, so the same database now
    reaches the first binding-scoped upsert and dies there with a bare
    `UndefinedColumn: column "vault_binding_id" of relation "objects" does not
    exist` — late, opaque, and part-way through a watcher tick. This is a
    behaviour change #4560 introduces, so #4560 supplies the preflight.

    Checks the two things the rekey depends on: that `vault_binding_id` exists,
    and that the primary key is `(vault_binding_id, id)`. It does not check for a
    leftover single-column unique index — the owning revision refuses to complete
    against one, so a database that reached this point cannot have one that the
    revision installed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              to_regclass('public.objects') IS NOT NULL AS table_exists,
              EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'objects'
                   AND column_name = 'vault_binding_id'
              ) AS binding_column_exists,
              COALESCE((
                SELECT array_agg(att.attname ORDER BY key.ordinality)
                  FROM pg_constraint con
                  JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality)
                    ON true
                  JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = key.attnum
                 WHERE con.conrelid = to_regclass('public.objects')
                   AND con.contype = 'p'
              ), ARRAY[]::text[]) AS primary_key
            """
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        table_exists = row["table_exists"]
        binding_column_exists = row["binding_column_exists"]
        primary_key = row["primary_key"]
    else:
        table_exists, binding_column_exists, primary_key = (
            (row[0], row[1], row[2]) if row else (False, False, [])
        )

    hint = (
        "This database predates Alembic revision d1e8a0c5f37b (MVR-05A1, "
        "#4560); run `alembic upgrade head` (scripts/run_migrations.sh) before "
        "starting a vault-sync producer."
    )
    if not table_exists:
        raise ObjectsSchemaMissingError(f"public.objects is missing. {hint}")
    if not binding_column_exists:
        raise ObjectsSchemaMissingError(
            f"public.objects has no `vault_binding_id` column. {hint}"
        )
    if list(primary_key or []) != ["vault_binding_id", "id"]:
        raise ObjectsSchemaMissingError(
            "public.objects has primary key "
            f"{list(primary_key or [])!r}, expected ['vault_binding_id', 'id']. "
            f"{hint}"
        )


def _autocreate_migration_owned_schema(conn: psycopg.Connection) -> None:
    """Create the migration-owned durable shape for test scratch databases.

    Inert outside tests: production DDL authority is the Alembic revision chain
    (`c7f4b1a83d29` for `file_state`, `d1e8a0c5f37b` for `objects` adoption,
    and `f8a05a9b0001` for the `agent_memories` binding key). The matching
    fail-loud preflight for a database that never
    ran the `file_state` revision is `assert_file_state_schema`, called from the
    vault-sync seam.

    A table that already exists is left completely alone, including its indexes.
    A scratch database stamped at an intermediate revision holds `objects` in an
    older shape, and issuing this group's statements against it would fail on a
    column the revision has not added yet — but more importantly, reshaping it
    here would make this fixture a second owner of a migration-owned table,
    which is the defect the slice removes.
    """
    if not _schema_autocreate_enabled():
        return
    for table, statements in _MIGRATION_OWNED_AUTOCREATE_SQL:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table,))
            row = cur.fetchone()
        present = (row.get("present") if isinstance(row, dict) else row[0]) if row else False
        if present:
            continue
        for statement in statements:
            with conn.cursor() as cur:
                cur.execute(statement)
    # `CREATE TABLE` above is skipped entirely on a scratch database that already
    # holds the pre-#4543 `path text PRIMARY KEY` shape, and every vault-sync
    # statement would then fail with an unexplained UndefinedColumn. Reuse the
    # same preflight so the test lane gets the "run migrations" hint instead.
    assert_file_state_schema(conn)


def _psycopg_dsn() -> str:
    """Allow DATABASE_URL overrides while keeping Pydantic defaults."""
    url = resolve_runtime_database_url(os.environ)
    return resolve_dsn(url or settings.db_dsn)


def conn_ro():
    """Return a read-only psycopg connection configured for dict-row results."""
    return _connect(_psycopg_dsn(), autocommit=True, row_factory=dict_row)


def conn_rw(*, connect_timeout: int | None = None):
    """Return a read/write psycopg connection configured for dict-row results.

    Pass ``connect_timeout`` (seconds) to bound the underlying socket connect for
    best-effort callers that must not stall when the DB host is unreachable.
    """
    kwargs: dict[str, object] = {"row_factory": dict_row}
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    conn = _connect(_psycopg_dsn(), **kwargs)
    global _SCHEMA_INITIALIZED
    if not _SCHEMA_INITIALIZED:
        ensure_schema(conn)
        conn.commit()
        _SCHEMA_INITIALIZED = True
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create test-fixture scratch schema. Issues no DDL in production.

    Until MVR-05A1 (#4560) this executed `app/db/migrations_obsidian.sql` on the
    first `conn_rw()` of every process. That file was a second DDL owner for
    `objects` and the only owner of `agent_memories`, and two of its statements
    dropped and re-added `objects_pkey` as `PRIMARY KEY (id)` unconditionally —
    so any binding-keyed primary key an Alembic revision installed was reverted
    at the next process boot, silently, because a single-binding instance has no
    duplicate ids for the re-add to trip over. Both tables are now owned by
    revision `d1e8a0c5f37b` and the bootstrap file is gone.

    What remains is the `STORE_SCHEMA_AUTOCREATE=1` create-on-demand path for
    scratch databases, the same KERNEL-04 (#2766) / KERNEL-05 (#2850) contract
    `store_*` and `outbox` use. Outside tests it returns without touching the
    connection, which is what `tests/architecture/test_durable_table_ownership.py
    ::test_no_durable_ddl_executes_outside_the_revision_chain` asserts.

    This function is a shared seam — `app/services/outbox.py::bootstrap` calls it
    too — so it deliberately does not gate on `assert_file_state_schema`; that
    preflight belongs to the vault-sync seam, whose table it guards.
    """
    _autocreate_migration_owned_schema(conn)
