"""MVR-05A1 (#4560): `objects`/`agent_memories` adoption and the `objects` rekey.

`objects` had two DDL owners: the Alembic chain created it, and
`app/db/migrations_obsidian.sql` re-shaped it on the first `conn_rw()` of every
process through `app/db/db.py::ensure_schema`. Two of that file's statements,

    ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;
    ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);

reverted any binding-keyed primary key a migration installed, at the next
process boot, with no error — a single-binding instance has no duplicate ids for
the re-add to trip over. `agent_memories` had no Alembic owner at all.

Alembic revision `d1e8a0c5f37b` adopts both tables and rekeys `objects` to
`(vault_binding_id, id)` with `objects_uuid_idx` scoped to
`UNIQUE (vault_binding_id, uuid)`; the same change deletes the bootstrap file
and the runtime path that executed it.

The migration exists for databases created by the **bootstrap** path, which
already hold rows, so every adoption case here starts from a database whose
`objects` table carries the historical bootstrap shape. A migration proven only
against a fresh `alembic upgrade head` database has not been tested against the
population it exists for.

`_LEGACY_BOOTSTRAP_OBJECTS_DDL` is reproduced inline because the production SQL
file no longer exists — that removal is the point of the slice. It is a
byte-for-byte copy of `app/db/migrations_obsidian.sql:19-50` as of `origin/main`
at a6e169134, and `test_the_restart_that_previously_reverted_the_key_still_does`
runs it as a negative control so these guards cannot pass vacuously.

Follows the fixture shape of `tests/migrations/test_file_state_adoption.py`
(MVR-05A0, #4543), the adoption this one completes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

# Head before `objects`/`agent_memories` became migration-owned: the MVR-05A0
# `file_state` adoption.
PRE_ADOPTION_HEAD = "c7f4b1a83d29"

# The MVR-05A1 adoption revision. Pinned explicitly (not "head") so later
# revisions adding DDL on top of `objects` do not move this target.
OBJECTS_ADOPTION_HEAD = "d1e8a0c5f37b"
MVR05A_RESIDUAL_HEAD = "f8a05a9b0001"

# Verbatim `app/db/migrations_obsidian.sql:19-50` before #4560 deleted the file.
# The `DROP CONSTRAINT`/`ADD CONSTRAINT` pair below is the defect this slice
# retires; it is kept here only so the tests can prove it is gone.
_LEGACY_BOOTSTRAP_OBJECTS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS public.agent_memories(
      id uuid PRIMARY KEY,
      run_id uuid NULL,
      layer text NOT NULL,
      payload jsonb NOT NULL DEFAULT '{}'::jsonb,
      provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS agent_memories_created_at_idx "
    "ON public.agent_memories (created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS public.objects(
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      uuid uuid,
      kind text NOT NULL,
      source_ref text,
      payload jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS id uuid",
    "ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS uuid uuid",
    "ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS source_ref text",
    "UPDATE public.objects SET id = uuid WHERE id IS NULL AND uuid IS NOT NULL",
    "UPDATE public.objects SET id = gen_random_uuid() WHERE id IS NULL",
    "UPDATE public.objects SET uuid = id WHERE uuid IS NULL",
    "ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey",
    "ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS objects_uuid_idx ON public.objects(uuid)",
    "CREATE INDEX IF NOT EXISTS objects_created_at_idx ON public.objects (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS objects_source_ref_idx ON public.objects (source_ref)",
)

ADOPTED_TABLES = ("objects", "agent_memories")


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


def _scratch_dsn(admin_dsn: str, dbname: str) -> str:
    base, _, _ = admin_dsn.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture
def scratch_db_factory():
    """Create throwaway databases on the configured Postgres; drop them after."""
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    created: list[str] = []

    def _create() -> str:
        name = f"scratch_mvr05a1_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        # The standard harness runs on a pgvector image; an earlier revision
        # declares `embedding VECTOR` unconditionally.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield _create

    for name in created:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:
            pass


def _alembic_upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _apply_legacy_bootstrap(dsn: str, *, pre_alembic_objects: bool = True) -> None:
    """Replay the retired runtime bootstrap DDL, exactly as `ensure_schema` did.

    `pre_alembic_objects` reproduces the *other* deployed lineage. On a database
    whose `objects` the bootstrap created before Alembic ever ran,
    `objects_uuid_idx` really is `UNIQUE (uuid)`. On a database where Alembic
    created the table first, the historical root `fe9a3607841f` had already made
    a **non-unique** index of that name, so the bootstrap's
    `CREATE UNIQUE INDEX IF NOT EXISTS` matched on name and silently no-opped —
    and replaying the bootstrap statements alone can therefore never produce the
    unique shape. Installing it explicitly is the only way to build the divergent
    starting state on a test database, because `fe9a3607841f` uses a plain
    `op.create_table` that would raise `DuplicateTable` against a genuinely
    bootstrap-first `objects`.
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in _LEGACY_BOOTSTRAP_OBJECTS_DDL:
            conn.execute(statement)
        if pre_alembic_objects:
            conn.execute("DROP INDEX IF EXISTS public.objects_uuid_idx")
            conn.execute("CREATE UNIQUE INDEX objects_uuid_idx ON public.objects(uuid)")


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/index shape of both adopted tables, normalized for comparison."""
    snapshot: dict[str, dict] = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for table in ADOPTED_TABLES:
            cur.execute(
                """
                SELECT column_name, ordinal_position, data_type, is_nullable,
                       COALESCE(column_default, '') AS column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            columns = [tuple(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT tc.constraint_name, kcu.column_name, kcu.ordinal_position
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """,
                (table,),
            )
            pk = [tuple(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = %s
                ORDER BY indexname
                """,
                (table,),
            )
            indexes = [tuple(row) for row in cur.fetchall()]
            snapshot[table] = {"columns": columns, "pk": pk, "indexes": indexes}
    return snapshot


def _primary_key(dsn: str) -> list[str]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            """
            SELECT array_agg(att.attname ORDER BY key.ordinality)
              FROM pg_constraint con
              JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality) ON true
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid AND att.attnum = key.attnum
             WHERE con.conrelid = to_regclass('public.objects') AND con.contype = 'p'
            """
        ).fetchone()
    return list((row[0] if row else None) or [])


def _primary_key_oid(dsn: str) -> int | None:
    """Identity of the `objects` primary-key constraint, not just its shape."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT oid FROM pg_constraint "
            "WHERE conrelid = to_regclass('public.objects') AND contype = 'p'"
        ).fetchone()
    return row[0] if row else None


def _uuid_index_def(dsn: str) -> str | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 'objects_uuid_idx'"
        ).fetchone()
    return row[0] if row else None


def _seed_legacy_rows(dsn: str, count: int = 4) -> tuple[list[tuple], list[str]]:
    """Insert rows through the *legacy* column list, as a deployed DB holds them."""
    objects_rows: list[tuple] = []
    memory_ids: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        for index in range(count):
            artifact_uuid = str(uuid.UUID(int=index + 1))
            row = (artifact_uuid, artifact_uuid, "note", f"source-{index}", f"/vault/n{index}.md")
            conn.execute(
                "INSERT INTO public.objects (id, uuid, kind, source_ref, payload, path) "
                "VALUES (%s, %s, %s, %s, '{}'::jsonb, %s)",
                row,
            )
            objects_rows.append(row)

            memory_id = str(uuid.UUID(int=1000 + index))
            conn.execute(
                "INSERT INTO public.agent_memories (id, run_id, layer, payload, provenance) "
                "VALUES (%s, NULL, 'short_term', %s::jsonb, %s::jsonb)",
                (memory_id, json.dumps({"n": index}), json.dumps({"agent": "test"})),
            )
            memory_ids.append(memory_id)
    return objects_rows, memory_ids


def _objects_rows(dsn: str) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT vault_binding_id, id::text, uuid::text, kind, source_ref, path "
            "FROM public.objects ORDER BY path"
        )
        return [tuple(row) for row in cur.fetchall()]


def _boot_a_fresh_process(dsn: str) -> subprocess.CompletedProcess:
    """Run `conn_rw()` in a genuinely new interpreter, as a container restart does.

    Resetting `_SCHEMA_INITIALIZED` in-process would exercise the same code, but
    the defect is specifically "at the next process boot", so this boots one.
    `STORE_SCHEMA_AUTOCREATE` is cleared: production posture, no fixture opt-in.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = dsn
    env.pop("DB_DSN", None)
    env.pop("STORE_SCHEMA_AUTOCREATE", None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.db.db import conn_rw\n"
            "conn = conn_rw()\n"
            "conn.close()\n"
            "print('booted')\n",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


# --------------------------------------------------------------------------- #
# AC: a binding-keyed constraint survives a process restart
# --------------------------------------------------------------------------- #


def test_binding_key_survives_schema_bootstrap(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rekey is still there after a real process boot runs `ensure_schema`.

    This is the defect, stated literally. A test that only checked the
    migration's immediate output would pass today against the broken behaviour:
    the revert happened at the *next* boot, and it succeeded silently.
    """
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    _seed_legacy_rows(dsn, count=2)
    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)

    assert _primary_key(dsn) == ["vault_binding_id", "id"]
    installed_pk_oid = _primary_key_oid(dsn)
    installed_index = _uuid_index_def(dsn)
    assert installed_index is not None and "UNIQUE" in installed_index.upper()

    # Boot a process. Twice — the per-process `_SCHEMA_INITIALIZED` latch means
    # one boot only ever ran the bootstrap once, so a second boot is the case
    # that actually reproduced in deployment.
    for attempt in range(2):
        result = _boot_a_fresh_process(dsn)
        assert result.returncode == 0, (
            f"boot {attempt} failed: {result.stdout}\n{result.stderr}"
        )
        assert "booted" in result.stdout

        assert _primary_key(dsn) == ["vault_binding_id", "id"], (
            "the binding-keyed primary key was reverted by a process boot; the "
            "runtime schema bootstrap is issuing DDL again"
        )
        # Not just the shape: an identical constraint that was dropped and
        # re-added would also read as `['vault_binding_id', 'id']`.
        assert _primary_key_oid(dsn) == installed_pk_oid, (
            "the primary key was dropped and recreated during a process boot"
        )
        assert _uuid_index_def(dsn) == installed_index

    # And the rows are still there afterwards.
    assert len(_objects_rows(dsn)) == 2


def test_the_restart_that_previously_reverted_the_key_still_does(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the retired DDL still reverts the key when replayed.

    Without this, `test_binding_key_survives_schema_bootstrap` could pass for the
    wrong reason — for instance if the boot never reached `ensure_schema` at all.
    Replaying the exact statements the bootstrap file used to run proves the
    guard has teeth and that removing them is what fixed it.
    """
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    assert _primary_key(dsn) == ["vault_binding_id", "id"]

    # Exactly what `ensure_schema` used to execute on the first `conn_rw()`.
    _apply_legacy_bootstrap(dsn)

    assert _primary_key(dsn) == ["id"], (
        "the historical bootstrap DDL no longer reverts the key, so the guard "
        "above proves nothing — re-derive it from the real defect"
    )


# --------------------------------------------------------------------------- #
# AC: two bindings can hold the same artifact UUID
# --------------------------------------------------------------------------- #


def test_two_bindings_share_an_artifact_uuid(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MVR-05A's AC-1 precondition, on the population it has to hold for.

    Both pre-rekey blockers are exercised separately, because they are not the
    same blocker and they do not both exist on every deployed database:

    - `PRIMARY KEY (id)` blocks the second binding on *every* lineage, because
      the vault-sync producer writes `id = uuid` (`app/services/vault_sync.py`)
      and the legacy backfill set `id = uuid` for older rows.
    - `objects_uuid_idx UNIQUE (uuid)` blocks it independently, and only on a
      database whose `objects` was created by the bootstrap SQL before Alembic
      ever ran — the shape `_apply_legacy_bootstrap` installs explicitly,
      because replaying the bootstrap statements alone cannot reach it.
    """
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)

    artifact_uuid = str(uuid.UUID(int=77))
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO public.objects (id, uuid, kind, payload, path) "
            "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
            (artifact_uuid, artifact_uuid, "/vault-a/shared.md"),
        )
        # Before the rekey a second binding cannot exist at all: the primary key
        # rejects it when the producer writes `id = uuid` ...
        with pytest.raises(psycopg.errors.UniqueViolation) as pk_violation:
            conn.execute(
                "INSERT INTO public.objects (id, uuid, kind, payload, path) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                (artifact_uuid, artifact_uuid, "/vault-b/shared.md"),
            )
        assert "objects_pkey" in str(pk_violation.value)
        # ... and the globally unique index rejects it even with a distinct id.
        with pytest.raises(psycopg.errors.UniqueViolation) as index_violation:
            conn.execute(
                "INSERT INTO public.objects (id, uuid, kind, payload, path) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                (str(uuid.UUID(int=78)), artifact_uuid, "/vault-b/shared.md"),
            )
        assert "objects_uuid_idx" in str(index_violation.value)

    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO public.objects (vault_binding_id, id, uuid, kind, payload, path) "
            "VALUES (%s, %s, %s, 'note', '{}'::jsonb, %s)",
            ("binding-second", artifact_uuid, artifact_uuid, "/vault-b/shared.md"),
        )
        bindings = conn.execute(
            "SELECT vault_binding_id FROM public.objects WHERE uuid = %s "
            "ORDER BY vault_binding_id",
            (artifact_uuid,),
        ).fetchall()

    from app.db.db import COMPATIBILITY_BINDING_ID

    assert [row[0] for row in bindings] == ["binding-second", COMPATIBILITY_BINDING_ID], bindings

    # Uniqueness is scoped, not removed: the same UUID twice inside one binding
    # is still a violation.
    with psycopg.connect(dsn, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO public.objects (vault_binding_id, id, uuid, kind, payload, path) "
                "VALUES (%s, %s, %s, 'note', '{}'::jsonb, %s)",
                ("binding-second", str(uuid.UUID(int=78)), artifact_uuid, "/vault-b/dup.md"),
            )


# --------------------------------------------------------------------------- #
# AC: existing rows survive adoption from a bootstrap-origin database
# --------------------------------------------------------------------------- #


def test_existing_rows_survive_adoption_from_bootstrap_origin(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A populated bootstrap-created database keeps every row in both tables."""
    from app.db.db import COMPATIBILITY_BINDING_ID

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    seeded_objects, seeded_memory_ids = _seed_legacy_rows(dsn, count=4)

    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)

    rows = _objects_rows(dsn)
    assert len(rows) == len(seeded_objects), (
        f"adoption lost objects rows: {len(seeded_objects)} before, {len(rows)} after. "
        "A migration that recreates the table empty is a failure even if every "
        "test passes."
    )
    for actual, expected in zip(rows, seeded_objects):
        binding_id, row_id, row_uuid, kind, source_ref, path = actual
        assert (row_id, row_uuid, kind, source_ref, path) == expected, actual
        assert binding_id == COMPATIBILITY_BINDING_ID, (
            "legacy rows must be attributed to the explicit compatibility "
            "binding, never guessed onto a registry binding"
        )

    with psycopg.connect(dsn) as conn:
        memory_rows = conn.execute(
            "SELECT id::text, layer, payload FROM public.agent_memories ORDER BY id"
        ).fetchall()
    assert [row[0] for row in memory_rows] == sorted(seeded_memory_ids), (
        "adoption lost agent_memories rows"
    )
    assert {row[1] for row in memory_rows} == {"short_term"}
    assert [row[2] for row in memory_rows] == [{"n": index} for index in range(4)]


# --------------------------------------------------------------------------- #
# AC: both origins converge
# --------------------------------------------------------------------------- #


def test_bootstrap_and_alembic_origins_converge(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bootstrap-shaped database and a fresh `alembic upgrade head` agree.

    The two sides must genuinely differ before the migration runs, or this
    compares a database against itself. They do, and the differences are
    asserted below: the bootstrap side carries `source_ref`, `agent_memories`,
    `objects_created_at_idx`, `objects_source_ref_idx`, and a **globally unique**
    `objects_uuid_idx`, while the Alembic side has none of those and a
    non-unique index of the same name.

    Scoped to the two adopted tables. The legacy bootstrap also dropped four
    v4.x views on every boot while the revision chain creates two of them, so a
    whole-schema comparison would diverge on a surface this slice does not own
    (see `docs/DB_SCHEMA.md :: Views / Helpers (legacy)`).
    """
    bootstrap_origin = scratch_db_factory()
    _alembic_upgrade(bootstrap_origin, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(bootstrap_origin)
    _seed_legacy_rows(bootstrap_origin, count=2)

    alembic_origin = scratch_db_factory()
    _alembic_upgrade(alembic_origin, monkeypatch, PRE_ADOPTION_HEAD)

    before_bootstrap = _schema_snapshot(bootstrap_origin)
    before_alembic = _schema_snapshot(alembic_origin)
    assert before_bootstrap != before_alembic, (
        "the two origins are already identical before the migration runs, so "
        "this test compares a database against itself"
    )
    assert before_alembic["agent_memories"]["columns"] == []
    assert "source_ref" not in [
        column[0] for column in before_alembic["objects"]["columns"]
    ]
    bootstrap_uuid_index = _uuid_index_def(bootstrap_origin)
    alembic_uuid_index = _uuid_index_def(alembic_origin)
    assert bootstrap_uuid_index is not None and "UNIQUE" in bootstrap_uuid_index.upper()
    assert alembic_uuid_index is not None and "UNIQUE" not in alembic_uuid_index.upper()

    _alembic_upgrade(bootstrap_origin, monkeypatch, "head")
    _alembic_upgrade(alembic_origin, monkeypatch, "head")

    bootstrap_shape = _schema_snapshot(bootstrap_origin)
    alembic_shape = _schema_snapshot(alembic_origin)

    assert bootstrap_shape == alembic_shape, (
        "bootstrap-origin and Alembic-origin schemas diverge:\n"
        f"bootstrap: {json.dumps(bootstrap_shape, indent=2, default=str)}\n"
        f"alembic:   {json.dumps(alembic_shape, indent=2, default=str)}"
    )
    for table in ADOPTED_TABLES:
        assert bootstrap_shape[table]["columns"], f"{table} missing after alembic upgrade head"
    assert [entry[1] for entry in bootstrap_shape["objects"]["pk"]] == [
        "vault_binding_id",
        "id",
    ]


# --------------------------------------------------------------------------- #
# Supporting guards
# --------------------------------------------------------------------------- #


def test_adoption_is_idempotent_over_a_bootstrap_created_table(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running the revision over an already-adopted database is a no-op."""
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    _seed_legacy_rows(dsn, count=2)
    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)

    adopted = _schema_snapshot(dsn)
    adopted_pk_oid = _primary_key_oid(dsn)

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.stamp(cfg, PRE_ADOPTION_HEAD)
    command.upgrade(cfg, OBJECTS_ADOPTION_HEAD)

    # An unconditional drop-and-re-add would also leave an identical snapshot;
    # the constraint oid is what proves the guards short-circuited instead.
    assert _schema_snapshot(dsn) == adopted, (
        "re-running the adoption revision changed an already-adopted schema:\n"
        f"first:  {json.dumps(adopted, indent=2, default=str)}\n"
        f"second: {json.dumps(_schema_snapshot(dsn), indent=2, default=str)}"
    )
    assert _primary_key_oid(dsn) == adopted_pk_oid, (
        "the re-run dropped and recreated the primary key instead of "
        "short-circuiting; the guard on the current key column list is not working"
    )
    assert len(_objects_rows(dsn)) == 2


def test_rekey_refuses_duplicate_binding_scoped_uuids(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Duplicate `objects.uuid` rows stop the migration loudly, not silently.

    `objects_uuid_idx` is *non-unique* on every database where Alembic created
    the table before the bootstrap ran (`fe9a3607841f` creates it that way and
    `CREATE UNIQUE INDEX IF NOT EXISTS` matches on name, so it silently no-ops),
    so duplicates are physically possible there. `app/objects/identity.py`
    already refuses to resolve them; the migration refuses too, rather than
    deduplicating by guess.
    """
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)

    shared_uuid = str(uuid.UUID(int=900))
    with psycopg.connect(dsn, autocommit=True) as conn:
        for index in range(2):
            conn.execute(
                "INSERT INTO public.objects (id, uuid, kind, payload, path) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                (str(uuid.UUID(int=900 + index + 1)), shared_uuid, f"/vault/dup{index}.md"),
            )

    with pytest.raises(Exception) as excinfo:
        _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    assert "duplicate (vault_binding_id, uuid) rows exist" in str(excinfo.value)

    # The refusal is not destructive: both rows are still there.
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM public.objects").fetchone() == (2,)


@pytest.mark.parametrize(
    ("index_name", "column"),
    [
        ("objects_uuid_unique_idx", "uuid"),
        ("objects_id_unique_idx", "id"),
    ],
)
def test_rekey_refuses_a_leftover_single_column_unique_index(
    index_name: str, column: str, scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single-column unique index under another name is caught, not ignored.

    The rekey replaces the index literally named `objects_uuid_idx`, so a unique
    index under any other name survives and silently re-imposes exactly the
    global uniqueness MVR-05A's AC-1 forbids — behind a key that looks correct.

    Both columns are checked, and `id` is not the lesser case: it is the second
    primary-key column, the structural analogue of `file_state`'s `path`, and the
    vault-sync producer writes `id = uuid`, so one unique row per `id` is one row
    per artifact UUID across every binding.
    `app/db/sql/objects_uuid_unrestrict.sql` created the `uuid` variant and this
    slice deleted it, but deleting the file cannot remove the index from a
    database where it was ever run.
    """
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"CREATE UNIQUE INDEX {index_name} ON public.objects({column})")

    with pytest.raises(Exception) as excinfo:
        _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    assert index_name in str(excinfo.value)

    # Non-destructive: the refusal leaves the database exactly as it was.
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='objects' AND column_name='vault_binding_id'"
        ).fetchone() is None
    assert _primary_key(dsn) == ["id"]

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"DROP INDEX public.{index_name}")
    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    assert _primary_key(dsn) == ["vault_binding_id", "id"]


def test_rekey_tolerates_indexes_that_do_not_re_impose_global_uniqueness(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stray-index guard must not false-positive on legitimate shapes."""
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        # Non-unique on uuid; unique but two-column; unique on an unrelated column.
        conn.execute("CREATE INDEX objects_uuid_plain_idx ON public.objects(uuid)")
        conn.execute(
            "CREATE UNIQUE INDEX objects_kind_uuid_idx ON public.objects(kind, uuid)"
        )
        conn.execute("CREATE UNIQUE INDEX objects_path_unique_idx ON public.objects(path)")

    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    assert _primary_key(dsn) == ["vault_binding_id", "id"]

    # And the binding-scoped index the revision itself creates is not flagged on
    # a re-run — the guard runs after the rekey, so it must ignore it.
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.stamp(cfg, PRE_ADOPTION_HEAD)
    command.upgrade(cfg, OBJECTS_ADOPTION_HEAD)
    assert _primary_key(dsn) == ["vault_binding_id", "id"]


def test_stale_objects_key_fails_loud_before_any_vault_sync_write(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database that never ran the adoption is rejected, not silently accepted.

    This is the behaviour change #4560 introduces and then closes. Before the
    slice, a database whose `objects` still had `PRIMARY KEY (id)` worked,
    because the runtime bootstrap reshaped the table on every process boot. With
    that bootstrap deleted, the same database reaches the first binding-scoped
    upsert and dies with a bare `UndefinedColumn` part-way through a watcher tick
    — exactly the failure mode `assert_file_state_schema` exists to prevent for
    the other table.
    """
    from app.db.db import (
        ObjectsSchemaMissingError,
        assert_file_state_schema,
        assert_objects_schema,
        ensure_schema,
    )

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _apply_legacy_bootstrap(dsn)
    _seed_legacy_rows(dsn, count=2)

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)
        conn.commit()
        # The `file_state` preflight passes on this database: its revision has
        # run. Only the `objects` half is stale, which is why a second preflight
        # is needed rather than reusing the first.
        assert_file_state_schema(conn)
        with pytest.raises(ObjectsSchemaMissingError, match="alembic upgrade head"):
            assert_objects_schema(conn)

    # The preflight is read-only: it must not repair or touch the rows it
    # refuses to run against.
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM public.objects").fetchone() == (2,)
    assert _primary_key(dsn) == ["id"]

    _alembic_upgrade(dsn, monkeypatch, OBJECTS_ADOPTION_HEAD)
    with psycopg.connect(dsn) as conn:
        assert_objects_schema(conn)


def test_autocreate_fixture_shape_matches_the_current_migration_head(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test-fixture create-on-demand produces exactly the migration's shape.

    The KERNEL-04 (#2766) / KERNEL-05 (#2850) contract allows a
    `STORE_SCHEMA_AUTOCREATE=1` create-on-demand path for scratch databases;
    parity with the migration is what keeps it from becoming a second source of
    truth now that it is the only DDL `app/db/db.py` issues at all.
    """
    from app.db.db import ensure_schema

    migrated = scratch_db_factory()
    _alembic_upgrade(migrated, monkeypatch, MVR05A_RESIDUAL_HEAD)

    autocreated = scratch_db_factory()  # no alembic, no tables at all
    monkeypatch.setenv("DATABASE_URL", autocreated)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(autocreated) as conn:
        ensure_schema(conn)
        conn.commit()

    assert _schema_snapshot(autocreated) == _schema_snapshot(migrated)


def test_autocreate_leaves_a_pre_adoption_database_alone(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture path must not touch `objects` on a partly-migrated database.

    A scratch database stamped at an intermediate revision holds `objects` in an
    older shape. `CREATE TABLE IF NOT EXISTS` no-ops there while every statement
    after it still runs, so the fixture would both fail on a column the revision
    has not added yet and — the real problem — become a second owner able to
    reshape a migration-owned table.
    """
    from app.db.db import ensure_schema

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    before = _schema_snapshot(dsn)

    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)
        conn.commit()

    after = _schema_snapshot(dsn)
    assert after["objects"] == before["objects"], (
        "the test-fixture autocreate reshaped a migration-owned objects table:\n"
        f"before: {json.dumps(before['objects'], indent=2, default=str)}\n"
        f"after:  {json.dumps(after['objects'], indent=2, default=str)}"
    )
    # `agent_memories` did not exist at that revision, so *its* group did run:
    # the skip is per table, not all-or-nothing.
    assert after["agent_memories"]["columns"], "agent_memories was not created"


def test_migration_and_runtime_agree_on_the_compatibility_binding_id() -> None:
    """One binding-identity scheme: the revision reuses MVR-05A0's literal."""
    from app.db.db import COMPATIBILITY_BINDING_ID, FILE_STATE_COMPATIBILITY_BINDING_ID

    assert FILE_STATE_COMPATIBILITY_BINDING_ID == COMPATIBILITY_BINDING_ID

    versions = REPO_ROOT / "app" / "alembic" / "versions"
    for head in (OBJECTS_ADOPTION_HEAD, PRE_ADOPTION_HEAD):
        revision = next(versions.glob(f"{head}_*.py"))
        text = revision.read_text(encoding="utf-8")
        assert f'_COMPATIBILITY_BINDING_ID = "{COMPATIBILITY_BINDING_ID}"' in text, head
