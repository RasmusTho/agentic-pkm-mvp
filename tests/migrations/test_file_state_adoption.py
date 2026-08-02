"""MVR-05A0 (#4543): `file_state` adoption into Alembic and its binding rekey.

`file_state` was created at runtime by `app/db/migrations_obsidian.sql` with
`path text PRIMARY KEY`, outside the revision chain. Alembic revision
`c7f4b1a83d29` adopts it in place and rekeys it to `(vault_binding_id, path)`.

The migration exists for databases created by the **bootstrap** path, which
already hold rows. A migration proven only against a fresh `alembic upgrade
head` database has not been tested against the population it exists for, so
every case here starts from a database whose `file_state` was created by the
historical bootstrap DDL, and one case proves both origins converge on the same
shape.

The legacy DDL is reproduced inline (`_LEGACY_BOOTSTRAP_FILE_STATE_DDL`) because
the production SQL file no longer contains it — that removal is the point of the
slice. It is a byte-for-byte copy of `app/db/migrations_obsidian.sql:5-13` as of
`origin/main` at 5ac2df38c.

Follows the fixture shape of `tests/migrations/test_outbox_schema_parity.py`
(KERNEL-05, #2850), the precedent this adoption mirrors.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

# Head before file_state became migration-owned.
PRE_ADOPTION_HEAD = "a9f3c2d7b6e1"

# The MVR-05A0 adoption revision. Pinned explicitly (not "head") so later
# revisions adding DDL on top of file_state do not move this target.
FILE_STATE_ADOPTION_HEAD = "c7f4b1a83d29"

# Verbatim `app/db/migrations_obsidian.sql:5-13` before #4543 removed it.
_LEGACY_BOOTSTRAP_FILE_STATE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS public.file_state (
      path text PRIMARY KEY,
      uuid text,
      fm_hash text,
      body_hash text,
      mtime timestamptz,
      last_seen timestamptz DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS file_state_uuid_idx ON public.file_state(uuid)",
)


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
        name = f"scratch_mvr05a0_{uuid.uuid4().hex[:12]}"
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


def _create_legacy_bootstrap_file_state(dsn: str) -> None:
    """Reproduce the pre-#4543 runtime-bootstrap `file_state` table."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in _LEGACY_BOOTSTRAP_FILE_STATE_DDL:
            conn.execute(statement)


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/index shape of `file_state`, normalized for comparison."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, ordinal_position, data_type, is_nullable,
                   COALESCE(column_default, '') AS column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'file_state'
            ORDER BY ordinal_position
            """
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
              AND tc.table_name = 'file_state'
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """
        )
        pk = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'file_state'
            ORDER BY indexname
            """
        )
        indexes = [tuple(row) for row in cur.fetchall()]
        # `objects.path` moved to the same revision, and the autocreate fixture
        # declares it too, so parity has to cover both halves rather than only
        # file_state.
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'objects' AND column_name = 'path'
            """
        )
        objects_path = [tuple(row) for row in cur.fetchall()]
    return {
        "columns": columns,
        "pk": pk,
        "indexes": indexes,
        "objects_path": objects_path,
    }


def _primary_key_oid(dsn: str) -> int | None:
    """Identity of the `file_state` primary-key constraint, not just its shape."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT oid FROM pg_constraint "
            "WHERE conrelid = to_regclass('public.file_state') AND contype = 'p'"
        ).fetchone()
    return row[0] if row else None


def _file_state_rows(dsn: str) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT vault_binding_id, path, uuid, fm_hash, body_hash, mtime
            FROM public.file_state
            ORDER BY path
            """
        )
        return [tuple(row) for row in cur.fetchall()]


def _seed_legacy_rows(dsn: str, count: int = 5) -> list[tuple]:
    """Insert rows through the *legacy* column list, as a deployed DB holds them."""
    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    seeded: list[tuple] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        for index in range(count):
            row = (
                f"/vault/note-{index}.md",
                str(uuid.UUID(int=index + 1)),
                f"fm-{index}",
                f"body-{index}",
                base + timedelta(minutes=index),
            )
            conn.execute(
                "INSERT INTO public.file_state (path, uuid, fm_hash, body_hash, mtime, last_seen) "
                "VALUES (%s, %s, %s, %s, %s, now())",
                row,
            )
            seeded.append(row)
    return seeded


# --------------------------------------------------------------------------- #
# AC-1: adoption is idempotent over a bootstrap-created table
# --------------------------------------------------------------------------- #


def test_adoption_is_idempotent_over_bootstrap_created_table(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adopting a bootstrap-created `file_state` converges, and re-running no-ops."""
    dsn = scratch_db_factory()

    # An existing deployed environment: lineage at the pre-adoption head, table
    # created by the historical runtime bootstrap DDL.
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _create_legacy_bootstrap_file_state(dsn)

    legacy_shape = _schema_snapshot(dsn)
    assert [column[0] for column in legacy_shape["columns"]] == [
        "path",
        "uuid",
        "fm_hash",
        "body_hash",
        "mtime",
        "last_seen",
    ]
    assert [entry[1] for entry in legacy_shape["pk"]] == ["path"]

    _alembic_upgrade(dsn, monkeypatch, FILE_STATE_ADOPTION_HEAD)
    adopted = _schema_snapshot(dsn)
    adopted_pk_oid = _primary_key_oid(dsn)

    assert [entry[1] for entry in adopted["pk"]] == ["vault_binding_id", "path"], adopted["pk"]
    # An *adopted* table must also carry no leftover uniqueness on `path` alone;
    # one would silently re-impose the one-binding-per-path constraint the rekey
    # exists to remove, on exactly the deployed population this migration serves.
    leftover_path_uniqueness = [
        index
        for index in adopted["indexes"]
        if "UNIQUE" in index[1].upper() and "(path)" in index[1].lower().replace(" ", "")
    ]
    assert leftover_path_uniqueness == [], leftover_path_uniqueness

    # Re-running the whole adoption step against the already-adopted database is
    # a no-op: this is what an operator re-running `alembic upgrade head`, or a
    # second container calling `scripts/run_migrations.sh`, actually does.
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.stamp(cfg, PRE_ADOPTION_HEAD)
    command.upgrade(cfg, FILE_STATE_ADOPTION_HEAD)

    # This proves *convergence*: an unconditional drop-and-re-add of the primary
    # key would also leave an identical snapshot. The constraint oid below is
    # what proves the DO block genuinely short-circuited instead.
    assert _schema_snapshot(dsn) == adopted, (
        "re-running the adoption revision changed an already-adopted schema:\n"
        f"first:  {json.dumps(adopted, indent=2, default=str)}\n"
        f"second: {json.dumps(_schema_snapshot(dsn), indent=2, default=str)}"
    )
    assert _primary_key_oid(dsn) == adopted_pk_oid, (
        "the re-run dropped and recreated the primary key instead of "
        "short-circuiting; the guard on the current key column list is not working"
    )


# --------------------------------------------------------------------------- #
# AC-2: existing rows survive adoption
# --------------------------------------------------------------------------- #


def test_existing_rows_survive_adoption(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database populated before the migration keeps every row and its sync state."""
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _create_legacy_bootstrap_file_state(dsn)
    seeded = _seed_legacy_rows(dsn, count=5)

    _alembic_upgrade(dsn, monkeypatch, FILE_STATE_ADOPTION_HEAD)

    rows = _file_state_rows(dsn)
    assert len(rows) == len(seeded), (
        f"adoption lost rows: {len(seeded)} before, {len(rows)} after. A migration "
        "that recreates file_state empty is a failure even if every test passes."
    )
    for actual, expected in zip(rows, seeded):
        binding_id, path, row_uuid, fm_hash, body_hash, mtime = actual
        assert (path, row_uuid, fm_hash, body_hash, mtime) == expected, actual
        assert binding_id == FILE_STATE_COMPATIBILITY_BINDING_ID, (
            "legacy rows must be attributed to the explicit compatibility "
            "binding, never guessed onto a registry binding"
        )


# --------------------------------------------------------------------------- #
# Both origins converge (the "population it exists for" requirement)
# --------------------------------------------------------------------------- #


def test_bootstrap_origin_and_alembic_origin_converge(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bootstrap-created database and a fresh `alembic upgrade head` agree."""
    bootstrap_origin = scratch_db_factory()
    _alembic_upgrade(bootstrap_origin, monkeypatch, PRE_ADOPTION_HEAD)
    _create_legacy_bootstrap_file_state(bootstrap_origin)
    _seed_legacy_rows(bootstrap_origin, count=2)
    _alembic_upgrade(bootstrap_origin, monkeypatch, "head")

    alembic_origin = scratch_db_factory()
    _alembic_upgrade(alembic_origin, monkeypatch, "head")

    bootstrap_shape = _schema_snapshot(bootstrap_origin)
    alembic_shape = _schema_snapshot(alembic_origin)

    assert bootstrap_shape == alembic_shape, (
        "bootstrap-origin and Alembic-origin file_state schemas diverge:\n"
        f"bootstrap: {json.dumps(bootstrap_shape, indent=2, default=str)}\n"
        f"alembic:   {json.dumps(alembic_shape, indent=2, default=str)}"
    )
    assert bootstrap_shape["columns"], "file_state missing after alembic upgrade head"


def test_runtime_bootstrap_cannot_create_or_mutate_file_state(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ensure_schema` has no `file_state`/`objects.path` DDL authority outside tests.

    It also fails loudly on a stale database instead of returning cleanly. Without
    that preflight, `conn_rw` would latch `_SCHEMA_INITIALIZED` and the operator
    would learn about the un-migrated schema only when the first vault-sync write
    raised an opaque invalid-conflict-target error inside a watcher tick
    (`AGENTS.md :: Required rules` -- Invariant -> producers).
    """
    from app.db.db import FileStateSchemaMissingError, assert_file_state_schema, ensure_schema

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)  # the legacy bootstrap alone must create neither surface
        conn.commit()
        with pytest.raises(FileStateSchemaMissingError, match="alembic upgrade head"):
            assert_file_state_schema(conn)

    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT to_regclass('public.file_state')").fetchone() == (None,), (
            "the legacy runtime bootstrap created the migration-owned file_state table"
        )
        objects_path = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='objects' AND column_name='path'"
        ).fetchone()
    assert objects_path is None, "the legacy runtime bootstrap created objects.path"

    # After the owning revision runs, both surfaces exist, the preflight passes,
    # and a further `ensure_schema` leaves them untouched.
    _alembic_upgrade(dsn, monkeypatch, FILE_STATE_ADOPTION_HEAD)
    before = _schema_snapshot(dsn)
    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)
        assert_file_state_schema(conn)
        conn.commit()
    assert _schema_snapshot(dsn) == before


def test_stale_file_state_key_fails_loud_before_any_vault_sync_write(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database with the *old* `path`-only key is rejected, not silently accepted.

    The table-missing case above is the easy half. This is the one that actually
    bites: a database whose bootstrap already created `file_state` but that never
    ran the adoption revision has the table, so an existence-only check would
    pass and the failure would surface as an invalid conflict target mid-tick.
    """
    from app.db.db import FileStateSchemaMissingError, assert_file_state_schema

    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, PRE_ADOPTION_HEAD)
    _create_legacy_bootstrap_file_state(dsn)
    _seed_legacy_rows(dsn, count=2)

    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    with psycopg.connect(dsn) as conn:
        with pytest.raises(FileStateSchemaMissingError, match=r"\['path'\]"):
            assert_file_state_schema(conn)

    # The preflight is read-only: it must not repair, drop, or touch the rows it
    # refuses to run against.
    with psycopg.connect(dsn) as conn:
        remaining = conn.execute("SELECT count(*) FROM public.file_state").fetchone()
    assert remaining == (2,)

    _alembic_upgrade(dsn, monkeypatch, FILE_STATE_ADOPTION_HEAD)
    with psycopg.connect(dsn) as conn:
        assert_file_state_schema(conn)


def test_autocreate_fixture_shape_matches_the_owning_revision(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test-fixture create-on-demand produces exactly the migration's shape.

    The KERNEL-04/KERNEL-05 contract allows a `STORE_SCHEMA_AUTOCREATE=1`
    create-on-demand path for scratch databases; parity with the migration is
    what keeps it from becoming a second source of truth.
    """
    from app.db.db import ensure_schema

    migrated = scratch_db_factory()
    _alembic_upgrade(migrated, monkeypatch, FILE_STATE_ADOPTION_HEAD)

    autocreated = scratch_db_factory()
    _alembic_upgrade(autocreated, monkeypatch, PRE_ADOPTION_HEAD)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(autocreated) as conn:
        ensure_schema(conn)
        conn.commit()

    assert _schema_snapshot(autocreated) == _schema_snapshot(migrated)


def test_autocreate_supplies_objects_path_on_a_virgin_database(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One `ensure_schema` is enough on a database that has no `objects` yet.

    `ALTER TABLE IF EXISTS public.objects ADD COLUMN IF NOT EXISTS path text`
    silently no-ops when `objects` does not exist. The test-fixture autocreate
    therefore has to run *after* the legacy bootstrap SQL that creates `objects`,
    not before it — otherwise a virgin scratch database ends the first
    `ensure_schema` with an `objects` table that has no `path` column, and only
    self-heals on some later call.
    """
    from app.db.db import ensure_schema

    dsn = scratch_db_factory()  # no alembic, no tables at all
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")

    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)
        conn.commit()

    with psycopg.connect(dsn) as conn:
        objects_path = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='objects' AND column_name='path'"
        ).fetchone()
        file_state = conn.execute("SELECT to_regclass('public.file_state')").fetchone()

    assert objects_path is not None, (
        "objects.path missing after a single ensure_schema on a virgin database"
    )
    assert file_state != (None,)


def test_migration_and_runtime_agree_on_the_compatibility_binding_id() -> None:
    """The literal duplicated into the revision matches the runtime constant."""
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID

    revision = next(
        (REPO_ROOT / "app" / "alembic" / "versions").glob(f"{FILE_STATE_ADOPTION_HEAD}_*.py")
    )
    text = revision.read_text(encoding="utf-8")
    assert f'_COMPATIBILITY_BINDING_ID = "{FILE_STATE_COMPATIBILITY_BINDING_ID}"' in text
