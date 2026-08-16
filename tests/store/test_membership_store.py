from __future__ import annotations

import uuid
from ipaddress import ip_address
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.store.membership_store import save_membership


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_BINDING_HEAD = "d1e8a0c5f37b"
PRE_SEED_HEAD = "f6a05a7b0001"
SEED_HEAD = "f7a05a4b0001"
MVR05A_RESIDUAL_HEAD = "f8a05a9b0001"
BINDING = COMPATIBILITY_BINDING_ID


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    if not _is_allowed_scratch_admin_dsn(dsn):
        pytest.fail("membership prerequisite tests require an explicit local dev or CI test target")
    return dsn


def _is_allowed_scratch_admin_dsn(dsn: str) -> bool:
    try:
        target = conninfo_to_dict(dsn)
    except Exception:
        return False
    host = target.get("host")
    hostaddr = target.get("hostaddr")
    port = target.get("port") or "5432"
    database = target.get("dbname")
    if target.get("service"):
        return False
    if hostaddr:
        try:
            address = ip_address(hostaddr)
        except ValueError:
            return False
        if not address.is_loopback:
            return False
        if host == "127.0.0.1" and hostaddr != "127.0.0.1":
            return False
    return (host == "127.0.0.1" and port == "15433" and database == "app_dev") or (
        host in {"localhost", "127.0.0.1"}
        and port in {"5432", "15434"}
        and database == "app_test"
    )


@pytest.fixture
def scratch_db_factory():
    admin = _admin_dsn()
    try:
        with psycopg.connect(admin, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    created: list[str] = []

    def create() -> str:
        name = f"scratch_membership_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created.append(name)
        dsn = make_url(admin).set(database=name).render_as_string(hide_password=False)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return dsn

    yield create
    for name in created:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _prepare_retained_lineage(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _upgrade(dsn, monkeypatch, PRE_BINDING_HEAD)
    with psycopg.connect(dsn) as conn:
        for (name,) in conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='membership'::regclass"
        ).fetchall():
            conn.execute(sql.SQL("ALTER TABLE membership DROP CONSTRAINT {}").format(sql.Identifier(name)))
        conn.execute("ALTER TABLE membership DROP COLUMN id")
        conn.execute("ALTER TABLE membership ADD PRIMARY KEY (object_id,set_id)")
        conn.execute(
            "ALTER TABLE membership ADD CONSTRAINT membership_object_id_fkey "
            "FOREIGN KEY (object_id) REFERENCES store_objects(object_id) ON DELETE CASCADE"
        )
        conn.execute(
            "ALTER TABLE membership ADD CONSTRAINT membership_set_id_fkey "
            "FOREIGN KEY (set_id) REFERENCES store_objects(object_id) ON DELETE CASCADE"
        )
    _upgrade(dsn, monkeypatch, PRE_SEED_HEAD)


def _published_set_id(dsn: str) -> uuid.UUID:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT id FROM sets WHERE name='published'").fetchone()
    assert row is not None
    return row[0]


def _revision(dsn: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return row[0]


@pytest.mark.pg
def test_published_set_is_seeded_before_projection(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated_dsn = scratch_db_factory()
    _upgrade(migrated_dsn, monkeypatch, SEED_HEAD)
    migrated_set_id = _published_set_id(migrated_dsn)

    fixture_dsn = scratch_db_factory()
    monkeypatch.setenv("DATABASE_URL", fixture_dsn)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    import app.stores.pg as pg_store

    monkeypatch.setattr(pg_store, "_TABLES_READY", False)
    pg_store._ensure_tables()
    fixture_set_id = _published_set_id(fixture_dsn)

    assert migrated_set_id == fixture_set_id == uuid.UUID(
        "afa60fd2-731a-5c30-ae25-07f56c115393"
    )


@pytest.mark.pg
def test_retained_lineage_has_binding_store_object(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _prepare_retained_lineage(dsn, monkeypatch)
    _upgrade(dsn, monkeypatch, SEED_HEAD)
    set_id = _published_set_id(dsn)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT kind, payload->>'name' FROM store_objects "
            "WHERE vault_binding_id=%s AND object_id=%s",
            (BINDING, set_id),
        ).fetchone() == ("membership-set", "published")

    existing_dsn = scratch_db_factory()
    _prepare_retained_lineage(existing_dsn, monkeypatch)
    existing_set_id = uuid.uuid4()
    with psycopg.connect(existing_dsn) as conn:
        conn.execute(
            "INSERT INTO sets(id,name,meta) VALUES (%s,'published','{\"legacy\":true}'::jsonb)",
            (existing_set_id,),
        )
        conn.execute(
            "INSERT INTO store_objects(vault_binding_id,object_id,kind,payload) "
            "VALUES (%s,%s,'legacy-set','{\"opaque\":true}'::jsonb)",
            (BINDING, existing_set_id),
        )
    _upgrade(existing_dsn, monkeypatch, SEED_HEAD)
    assert _published_set_id(existing_dsn) == existing_set_id
    with psycopg.connect(existing_dsn) as conn:
        assert conn.execute(
            "SELECT kind,payload FROM store_objects "
            "WHERE vault_binding_id=%s AND object_id=%s",
            (BINDING, existing_set_id),
        ).fetchone() == ("legacy-set", {"opaque": True})


@pytest.mark.pg
def test_seed_collision_rolls_back_and_retry_recovers(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_SEED_HEAD)
    collision_id = uuid.UUID("afa60fd2-731a-5c30-ae25-07f56c115393")
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO sets(id,name) VALUES (%s,'unrelated-existing-set')",
            (collision_id,),
        )

    with pytest.raises(DBAPIError, match="sets_pkey"):
        _upgrade(dsn, monkeypatch, SEED_HEAD)
    assert _revision(dsn) == PRE_SEED_HEAD
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM sets WHERE name='published'").fetchone() == (0,)
        conn.execute("DELETE FROM sets WHERE id=%s", (collision_id,))

    _upgrade(dsn, monkeypatch, SEED_HEAD)
    assert _published_set_id(dsn) == collision_id


@pytest.mark.pg
def test_unsupported_lineage_rolls_back_without_partial_seed(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_SEED_HEAD)
    with psycopg.connect(dsn) as conn:
        (primary_key,) = conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid='membership'::regclass AND contype='p'"
        ).fetchone()
        conn.execute(
            sql.SQL("ALTER TABLE membership DROP CONSTRAINT {}").format(
                sql.Identifier(primary_key)
            )
        )
        conn.execute("ALTER TABLE membership ADD PRIMARY KEY (vault_binding_id,object_id)")

    with pytest.raises(DBAPIError, match="unsupported primary-key lineage"):
        _upgrade(dsn, monkeypatch, SEED_HEAD)
    assert _revision(dsn) == PRE_SEED_HEAD
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM sets WHERE name='published'").fetchone() == (0,)


@pytest.mark.pg
def test_concurrent_set_writer_blocks_seed_and_retry_recovers(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_SEED_HEAD)
    blocker = psycopg.connect(dsn)
    try:
        blocker.execute("LOCK TABLE sets IN ROW EXCLUSIVE MODE")
        monkeypatch.setenv("PGOPTIONS", "-c lock_timeout=250ms")
        with pytest.raises(DBAPIError, match="lock timeout"):
            _upgrade(dsn, monkeypatch, SEED_HEAD)
        assert _revision(dsn) == PRE_SEED_HEAD
    finally:
        blocker.close()
        monkeypatch.delenv("PGOPTIONS", raising=False)

    _upgrade(dsn, monkeypatch, SEED_HEAD)
    assert _published_set_id(dsn)


@pytest.mark.pg
def test_retained_endpoint_deletion_refuses_partial_projection(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _prepare_retained_lineage(dsn, monkeypatch)
    _upgrade(dsn, monkeypatch, MVR05A_RESIDUAL_HEAD)
    set_id = _published_set_id(dsn)
    object_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects(vault_binding_id,object_id,kind,payload) "
            "VALUES (%s,%s,'note','{}'::jsonb)",
            (BINDING, object_id),
        )
        conn.execute(
            "DELETE FROM store_objects WHERE vault_binding_id=%s AND object_id=%s",
            (BINDING, set_id),
        )

    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="membership_set_id_fkey"):
        save_membership(str(object_id), "published")
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM membership WHERE vault_binding_id=%s AND object_id=%s",
            (BINDING, object_id),
        ).fetchone() == (0,)


class _MissingSetCursor:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, _params=None):
        self.sql.append(statement)

    def fetchone(self):
        if self.sql[-1] == (
            "SELECT id FROM sets WHERE vault_binding_id = %s AND name = %s"
        ):
            return None
        if "public.sets" in self.sql[-1]:
            return {"primary_key": ["vault_binding_id", "id"]}
        return {"primary_key": ["vault_binding_id", "id"]}


class _Connection:
    def __init__(self, cursor: _MissingSetCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self._cursor


@pytest.mark.not_pg
def test_missing_membership_prerequisite_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _MissingSetCursor()
    monkeypatch.setattr("app.store.membership_store.conn_rw", lambda: _Connection(cursor))

    with pytest.raises(RuntimeError, match="run alembic upgrade head"):
        save_membership("object", "published")

    assert not any("INSERT INTO membership" in statement for statement in cursor.sql)
