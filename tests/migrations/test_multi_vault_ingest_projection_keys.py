"""Executable PostgreSQL proofs for MVR-05A4 ingest identity conversion."""

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


pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_BINDING_HEAD = "d1e8a0c5f37b"
PRE_INGEST_HEAD = "e7b4c9d2a6f1"
INGEST_HEAD = "f4a05a4b0001"
BINDING = COMPATIBILITY_BINDING_ID


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    if not _is_allowed_scratch_admin_dsn(dsn):
        pytest.fail("MVR-05A4 scratch tests require an explicit local dev or CI test target")
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
        host in {"localhost", "127.0.0.1"} and port == "5432" and database == "app_test"
    )


@pytest.mark.parametrize(
    ("dsn", "allowed"),
    (
        ("postgresql://app:x@127.0.0.1:15433/app_dev", True),
        ("postgresql://app:x@localhost:5432/app_test", True),
        ("postgresql://app:x@localhost:5432/app_test?hostaddr=127.0.0.1", True),
        ("postgresql://app:x@127.0.0.1:15432/app", False),
        ("postgresql:///app_test", False),
        ("service=app_test", False),
        ("postgresql://app:x@localhost:5432/app_test?service=foreign", False),
        ("postgresql://app:x@localhost:5432/app_test?hostaddr=203.0.113.10", False),
        ("postgresql://app:x@127.0.0.1:5432/app_test?hostaddr=::1", False),
    ),
)
def test_scratch_database_factory_accepts_only_explicit_nonprod_targets(
    dsn: str, allowed: bool
) -> None:
    assert _is_allowed_scratch_admin_dsn(dsn) is allowed


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
        name = f"scratch_mvr05a4_{uuid.uuid4().hex[:12]}"
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
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            assert conn.execute(
                "SELECT count(*) FROM pg_database WHERE datname=%s", (name,)
            ).fetchone() == (0,)


def _upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _pk(conn: psycopg.Connection, table: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT a.attname FROM pg_constraint c "
            "JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum "
            "WHERE c.conrelid=(%s)::regclass AND c.contype='p' ORDER BY k.ordinality",
            (f"public.{table}",),
        ).fetchall()
    ]


def _fk(conn: psycopg.Connection, table: str, column: str) -> tuple:
    row = conn.execute(
        "SELECT array_agg(a.attname ORDER BY k.ordinality), p.relname, "
        "array_agg(pa.attname ORDER BY k.ordinality), c.confupdtype::text, "
        "c.confdeltype::text, c.confmatchtype::text, c.condeferrable, c.condeferred "
        "FROM pg_constraint c JOIN pg_class p ON p.oid=c.confrelid "
        "JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true "
        "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum "
        "JOIN pg_attribute pa ON pa.attrelid=c.confrelid AND pa.attnum=c.confkey[k.ordinality] "
        "WHERE c.conrelid=(%s)::regclass AND c.contype='f' "
        "GROUP BY c.oid,p.relname HAVING %s=ANY(array_agg(a.attname))",
        (f"public.{table}", column),
    ).fetchone()
    assert row is not None
    return (list(row[0]), row[1], list(row[2]), *row[3:])


def _seed_fresh_parent(conn: psycopg.Connection) -> tuple[uuid.UUID, uuid.UUID]:
    object_id, set_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        "INSERT INTO objects (id,uuid,kind,payload,vault_binding_id) "
        "VALUES (%s,%s,'note','{}'::jsonb,%s)",
        (object_id, object_id, BINDING),
    )
    conn.execute(
        "INSERT INTO store_objects (vault_binding_id,object_id,kind,payload) "
        "VALUES (%s,%s,'note','{}'::jsonb)",
        (BINDING, object_id),
    )
    conn.execute("INSERT INTO sets (id,name) VALUES (%s,'published')", (set_id,))
    return object_id, set_id


def _prepare_retained_historical_lineage(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID]:
    _upgrade(dsn, monkeypatch, PRE_BINDING_HEAD)
    with psycopg.connect(dsn) as conn:
        constraints = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='membership'::regclass"
        ).fetchall()
        for (name,) in constraints:
            conn.execute(
                sql.SQL("ALTER TABLE membership DROP CONSTRAINT {}").format(sql.Identifier(name))
            )
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
        first, second = uuid.uuid4(), uuid.uuid4()
        for oid in (first, second):
            conn.execute(
                "INSERT INTO objects (id,uuid,kind,payload,vault_binding_id) "
                "VALUES (%s,%s,'note','{}'::jsonb,%s)",
                (oid, oid, BINDING),
            )
            conn.execute(
                "INSERT INTO store_objects (object_id,kind,payload) VALUES (%s,'note','{}'::jsonb)",
                (oid,),
            )
        conn.execute("INSERT INTO membership (object_id,set_id) VALUES (%s,%s)", (first, second))
    return first, second


def test_membership_key_and_chunk_fk_follow_effective_lineage(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        object_id, set_id = _seed_fresh_parent(conn)
        chunk_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO chunks (id,vault_binding_id,object_id,idx,offset_start,offset_end,text) "
            "VALUES (%s,%s,%s,0,0,1,'x')",
            (chunk_id, BINDING, object_id),
        )
        conn.execute(
            "INSERT INTO embeddings (id,vault_binding_id,object_id,chunk_id,dim) "
            "VALUES (%s,%s,%s,%s,3)",
            (uuid.uuid4(), BINDING, object_id, chunk_id),
        )
        conn.execute(
            "INSERT INTO membership (id,vault_binding_id,object_id,set_id) VALUES (%s,%s,%s,%s)",
            (uuid.uuid4(), BINDING, object_id, set_id),
        )
    _upgrade(dsn, monkeypatch, INGEST_HEAD)
    written_object, written_set = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id,uuid,kind,payload,vault_binding_id) "
            "VALUES (%s,%s,'note','{}'::jsonb,%s)",
            (written_object, written_object, BINDING),
        )
        conn.execute(
            "INSERT INTO store_objects (vault_binding_id,object_id,kind,payload) "
            "VALUES (%s,%s,'note','{}'::jsonb)",
            (BINDING, written_object),
        )
        conn.execute("INSERT INTO sets (id,name) VALUES (%s,'writer-proof')", (written_set,))
    save_membership(str(written_object), str(written_set))
    with psycopg.connect(dsn) as conn:
        assert _pk(conn, "membership") == ["vault_binding_id", "id"]
        assert _pk(conn, "chunks") == ["id"]
        assert _pk(conn, "embeddings") == ["id"]
        assert _pk(conn, "relations") == ["id"]
        assert _fk(conn, "embeddings", "chunk_id") == (
            ["vault_binding_id", "chunk_id"],
            "chunks",
            ["vault_binding_id", "id"],
            "a",
            "c",
            "s",
            False,
            False,
        )
        assert _fk(conn, "membership", "set_id")[1:3] == ("sets", ["id"])
        assert conn.execute(
            "SELECT id IS NOT NULL FROM membership "
            "WHERE vault_binding_id=%s AND object_id=%s AND set_id=%s",
            (BINDING, written_object, written_set),
        ).fetchone() == (True,)


def test_retained_historical_membership_lineage_is_rekeyed(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    first, second = _prepare_retained_historical_lineage(dsn, monkeypatch)
    _upgrade(dsn, monkeypatch, INGEST_HEAD)
    writer_object, writer_set = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        for oid in (writer_object, writer_set):
            conn.execute(
                "INSERT INTO objects (id,uuid,kind,payload,vault_binding_id) "
                "VALUES (%s,%s,'note','{}'::jsonb,%s)",
                (oid, oid, BINDING),
            )
            conn.execute(
                "INSERT INTO store_objects (vault_binding_id,object_id,kind,payload) "
                "VALUES (%s,%s,'note','{}'::jsonb)",
                (BINDING, oid),
            )
    save_membership(str(writer_object), str(writer_set))
    with psycopg.connect(dsn) as conn:
        assert _pk(conn, "membership") == ["vault_binding_id", "object_id", "set_id"]
        assert _fk(conn, "membership", "set_id")[:3] == (
            ["vault_binding_id", "set_id"],
            "store_objects",
            ["vault_binding_id", "object_id"],
        )
        assert conn.execute(
            "SELECT vault_binding_id,object_id,set_id FROM membership"
        ).fetchone() == (BINDING, first, second)
        assert conn.execute(
            "SELECT count(*) FROM membership "
            "WHERE vault_binding_id=%s AND object_id=%s AND set_id=%s",
            (BINDING, writer_object, writer_set),
        ).fetchone() == (1,)


def test_ingest_rekey_reuses_delivered_binding_or_fails_unchanged(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "CREATE TABLE unknown_chunk_consumer (id uuid PRIMARY KEY, chunk_id uuid REFERENCES chunks(id))"
        )
        before_pk = _pk(conn, "membership")
    with pytest.raises(DBAPIError, match="unknown chunks inbound FK"):
        _upgrade(dsn, monkeypatch, INGEST_HEAD)
    with pytest.raises(RuntimeError, match="unsupported membership primary key"):
        save_membership(str(uuid.uuid4()), str(uuid.uuid4()))
    with psycopg.connect(dsn) as conn:
        assert _pk(conn, "membership") == before_pk == ["id"]
        assert conn.execute(
            "SELECT count(*) FROM pg_constraint WHERE conrelid='chunks'::regclass "
            "AND contype='u' AND conkey=ARRAY[(SELECT attnum FROM pg_attribute "
            "WHERE attrelid='chunks'::regclass AND attname='vault_binding_id'), "
            "(SELECT attnum FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='id')]::smallint[]"
        ).fetchone() == (0,)
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PRE_INGEST_HEAD,
        )


def test_missing_delivered_object_endpoint_refuses_before_rekey(
    scratch_db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        object_fk = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='membership'::regclass "
            "AND contype='f' AND conkey=ARRAY["
            "(SELECT attnum FROM pg_attribute WHERE attrelid='membership'::regclass "
            "AND attname='vault_binding_id'),"
            "(SELECT attnum FROM pg_attribute WHERE attrelid='membership'::regclass "
            "AND attname='object_id')]::smallint[]"
        ).fetchone()
        assert object_fk is not None
        conn.execute(
            sql.SQL("ALTER TABLE membership DROP CONSTRAINT {}").format(
                sql.Identifier(object_fk[0])
            )
        )
    with pytest.raises(DBAPIError, match="missing delivered object endpoint"):
        _upgrade(dsn, monkeypatch, INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        assert _pk(conn, "membership") == ["id"]
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PRE_INGEST_HEAD,
        )


@pytest.mark.parametrize(
    ("update_action", "delete_action", "deferrability", "expected"),
    (
        ("RESTRICT", "SET NULL", "DEFERRABLE INITIALLY DEFERRED", ("r", "n", True, True)),
        ("CASCADE", "SET DEFAULT", "NOT DEFERRABLE", ("c", "d", False, False)),
    ),
)
def test_chunk_fk_preserves_supported_action_and_deferral_semantics(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    update_action: str,
    delete_action: str,
    deferrability: str,
    expected: tuple[str, str, bool, bool],
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        conn.execute("ALTER TABLE embeddings DROP CONSTRAINT embeddings_chunk_id_fkey")
        conn.execute(
            "ALTER TABLE embeddings ADD CONSTRAINT embeddings_chunk_id_fkey "
            "FOREIGN KEY (chunk_id) REFERENCES chunks(id) MATCH SIMPLE "
            f"ON UPDATE {update_action} ON DELETE {delete_action} {deferrability}"
        )
        object_id, _ = _seed_fresh_parent(conn)
        chunk_id = uuid.uuid4()
        embedding_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO chunks(id,vault_binding_id,object_id,idx,offset_start,offset_end,text) "
            "VALUES (%s,%s,%s,0,0,1,'x')",
            (chunk_id, BINDING, object_id),
        )
        conn.execute(
            "INSERT INTO embeddings(id,vault_binding_id,object_id,chunk_id,dim) "
            "VALUES (%s,%s,%s,%s,3)",
            (embedding_id, BINDING, object_id, chunk_id),
        )
    _upgrade(dsn, monkeypatch, INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        fk = _fk(conn, "embeddings", "chunk_id")
        assert (fk[3], fk[4], fk[6], fk[7]) == expected
        conn.execute("DELETE FROM chunks WHERE vault_binding_id=%s AND id=%s", (BINDING, chunk_id))
        assert conn.execute(
            "SELECT vault_binding_id,chunk_id FROM embeddings WHERE id=%s", (embedding_id,)
        ).fetchone() == (BINDING, None)


@pytest.mark.parametrize(
    ("clause", "message"),
    (
        ("MATCH FULL ON UPDATE NO ACTION ON DELETE CASCADE", "MATCH type"),
        ("MATCH SIMPLE ON UPDATE SET NULL ON DELETE CASCADE", "ON UPDATE action"),
    ),
)
def test_chunk_fk_refuses_unpreservable_semantics_before_change(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
    clause: str,
    message: str,
) -> None:
    dsn = scratch_db_factory()
    _upgrade(dsn, monkeypatch, PRE_INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        conn.execute("ALTER TABLE embeddings DROP CONSTRAINT embeddings_chunk_id_fkey")
        conn.execute(
            "ALTER TABLE embeddings ADD CONSTRAINT embeddings_chunk_id_fkey "
            f"FOREIGN KEY (chunk_id) REFERENCES chunks(id) {clause}"
        )
    with pytest.raises(DBAPIError, match=message):
        _upgrade(dsn, monkeypatch, INGEST_HEAD)
    with psycopg.connect(dsn) as conn:
        assert _pk(conn, "membership") == ["id"]
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PRE_INGEST_HEAD,
        )
