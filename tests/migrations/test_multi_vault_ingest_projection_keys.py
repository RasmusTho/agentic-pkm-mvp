"""Executable PostgreSQL proofs for MVR-05A4 ingest identity conversion."""

from __future__ import annotations

import uuid
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
    target = conninfo_to_dict(dsn)
    if (
        target.get("host") != "127.0.0.1"
        or target.get("port") != "15433"
        or target.get("dbname") != "app_dev"
    ):
        pytest.fail("MVR-05A4 scratch tests require the explicit local dev database target")
    return dsn


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
    _upgrade(dsn, monkeypatch, PRE_BINDING_HEAD)
    with psycopg.connect(dsn) as conn:
        constraints = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='membership'::regclass"
        ).fetchall()
        for (name,) in constraints:
            conn.execute(f'ALTER TABLE membership DROP CONSTRAINT "{name}"')
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
