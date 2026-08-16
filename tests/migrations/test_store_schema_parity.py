"""Store schema parity between Alembic and `_ensure_tables()`.

Audit invariant I-S3: one schema authority per database. The current
MVR-05A3 head must produce exactly the store-table shape the audited
`_ensure_tables()` bootstrap produced, and re-running migrations on an
existing environment must be a no-op (no data movement).

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/STORE_SCHEMA_IN_MIGRATIONS.md
MVR-05A3 adds a second parity assertion at the current composite-key head;
the historical KERNEL-04 tests remain pinned to their owning revision.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

STORE_TABLES = (
    "store_objects",
    "store_vector_index",
    "store_relations",
    "store_relation_memberships",
    "vector_index_meta",
)

# Keep store-table parity pinned to its owning revision. Child binding parity
# follows the latest revision that changes a child binding invariant; MVR-05A5
# makes the previously nullable decisions binding final and NOT NULL.
STORE_SCHEMA_HEAD = "e6c4a2b8d1f3"
STORE_BINDING_HEAD = "f8a05a9b0001"
MINIMUM_CHILD_TABLES = (
    "chunks",
    "embeddings",
    "relations",
    "membership",
    "decisions",
    "audit",
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
def scratch_db_factory(monkeypatch: pytest.MonkeyPatch):
    """Create throwaway databases on the configured Postgres; drop them after."""
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    created: list[str] = []

    def _create() -> str:
        name = f"scratch_kernel04_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        dsn = _scratch_dsn(admin_dsn, name)
        # The standard harness runs on a pgvector image (docker-compose.yaml:
        # pgvector/pgvector); the pre-existing 202510241200 migration declares
        # `embedding VECTOR` unconditionally, so the extension must exist in
        # the target database before `alembic upgrade`. ENABLE_VECTOR stays at
        # its repo-wide default (unset): no environment sets it, and its
        # ivfflat branch does not run in any real channel.
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


def _run_ensure_tables(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.stores.pg as pg_module

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)
    pg_module._ensure_tables()
    monkeypatch.setattr(pg_module, "_TABLES_READY", False)


def _schema_snapshot(dsn: str) -> dict:
    """Column/PK/CHECK/index shape of the five store tables, normalized for comparison."""
    snapshot: dict[str, dict] = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for table in STORE_TABLES:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable,
                           COALESCE(column_default, '') AS column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY column_name
                    """,
                    (table,),
                )
                columns = [tuple(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT kcu.column_name
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
                pk = [row[0] for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = %s::regclass AND contype = 'c'
                    ORDER BY 1
                    """,
                    (f"public.{table}",),
                )
                checks = sorted(row[0] for row in cur.fetchall())
                # AC1 promises index parity, not only columns/constraints
                # (pg_indexes covers PK-backing indexes and any secondary ones).
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
                snapshot[table] = {
                    "columns": columns,
                    "pk": pk,
                    "checks": checks,
                    "indexes": indexes,
                }
    return snapshot


def _binding_shape_snapshot(dsn: str) -> dict:
    """Binding columns, store PKs, and canonical child FKs at the current head."""
    tables = (*STORE_TABLES, *MINIMUM_CHILD_TABLES)
    snapshot: dict[str, dict] = {}
    with psycopg.connect(dsn) as conn:
        for table in tables:
            columns = conn.execute(
                "SELECT column_name, data_type, is_nullable, COALESCE(column_default, '') "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table,),
            ).fetchall()
            pk = conn.execute(
                "SELECT a.attname FROM pg_constraint c "
                "JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "WHERE c.conrelid = (%s)::regclass AND c.contype = 'p' ORDER BY k.ordinality",
                (f"public.{table}",),
            ).fetchall()
            fks = conn.execute(
                """
                SELECT c.conname,
                       array_agg(child.attname ORDER BY ck.ordinality),
                       parent.relname,
                       array_agg(parent_att.attname ORDER BY ck.ordinality),
                       c.confupdtype::text, c.confdeltype::text,
                       c.condeferrable, c.condeferred,
                       COALESCE((
                           SELECT array_agg(set_att.attname ORDER BY sk.ordinality)
                           FROM unnest(c.confdelsetcols) WITH ORDINALITY sk(attnum, ordinality)
                           JOIN pg_attribute set_att
                             ON set_att.attrelid = c.conrelid AND set_att.attnum = sk.attnum
                       ), ARRAY[]::name[])
                  FROM pg_constraint c
                  JOIN pg_class parent ON parent.oid = c.confrelid
                  JOIN unnest(c.conkey) WITH ORDINALITY ck(attnum, ordinality) ON true
                  JOIN pg_attribute child
                    ON child.attrelid = c.conrelid AND child.attnum = ck.attnum
                  JOIN pg_attribute parent_att
                    ON parent_att.attrelid = c.confrelid
                   AND parent_att.attnum = c.confkey[ck.ordinality]
                 WHERE c.conrelid = (%s)::regclass AND c.contype = 'f'
                 GROUP BY c.oid, parent.relname ORDER BY c.conname
                """,
                (f"public.{table}",),
            ).fetchall()
            checks = conn.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = (%s)::regclass AND contype = 'c' ORDER BY 1",
                (f"public.{table}",),
            ).fetchall()
            snapshot[table] = {
                "columns": [tuple(row) for row in columns],
                "pk": [row[0] for row in pk],
                "fks": [
                    (
                        row[0],
                        list(row[1]),
                        row[2],
                        list(row[3]),
                        *row[4:8],
                        list(row[8]),
                    )
                    for row in fks
                ],
                "checks": sorted(row[0] for row in checks),
            }
    return snapshot


def _minimum_child_binding_shape(snapshot: dict) -> dict:
    """Normalize the current child binding/key invariant for parity.

    MVR-05A5 retains ownership of rebuild semantics, so this projection compares
    the namespace column, effective PK, every effective FK, and the
    nullable-receipt check — not unrelated child payload columns.
    """
    endpoints = {
        "chunks": ("object_id",),
        "embeddings": ("object_id",),
        "relations": ("src_id", "dst_id"),
        "membership": ("object_id", "set_id"),
        "decisions": ("object_id",),
        "audit": ("object_id",),
    }
    result: dict[str, dict] = {}
    for table, endpoint_names in endpoints.items():
        row = snapshot[table]
        columns = {column[0]: tuple(column[1:]) for column in row["columns"]}
        result[table] = {
            "binding_column": columns.get("vault_binding_id"),
            "endpoint_columns": {
                endpoint: columns.get(endpoint) for endpoint in endpoint_names
            },
            "pk": row["pk"],
            # Constraint names are not semantics; everything after the name is.
            "fks": sorted(
                tuple(json.dumps(value, default=str) for value in fk[1:])
                for fk in row["fks"]
            ),
            "checks": row["checks"] if table in {"decisions", "audit"} else [],
        }
    return result


def test_fresh_db_parity(scratch_db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh-DB `alembic upgrade <STORE_SCHEMA_HEAD>` == the audited `_ensure_tables()` shape."""
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()

    _alembic_upgrade(migrated, monkeypatch, STORE_SCHEMA_HEAD)
    _run_ensure_tables(bootstrapped, monkeypatch)

    migrated_shape = _schema_snapshot(migrated)
    bootstrapped_shape = _schema_snapshot(bootstrapped)

    assert migrated_shape == bootstrapped_shape, (
        "Alembic-produced store schema diverges from _ensure_tables() shape:\n"
        f"alembic: {json.dumps(migrated_shape, indent=2, default=str)}\n"
        f"bootstrap: {json.dumps(bootstrapped_shape, indent=2, default=str)}"
    )
    # Every table actually exists (non-empty column sets).
    for table in STORE_TABLES:
        assert migrated_shape[table]["columns"], f"{table} missing after alembic upgrade"


def test_upgrade_idempotent_on_existing(scratch_db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reapplying the current head is a schema/data no-op."""
    dsn = scratch_db_factory()
    _alembic_upgrade(dsn, monkeypatch, STORE_SCHEMA_HEAD)
    object_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects "
            "(vault_binding_id, object_id, kind, source_ref, payload) "
            "VALUES ('binding-a', %s, 'note', 'test://existing', '{}'::jsonb)",
            (object_id,),
        )

    before = _schema_snapshot(dsn)
    _alembic_upgrade(dsn, monkeypatch, STORE_SCHEMA_HEAD)
    after = _schema_snapshot(dsn)

    assert before == after, "Migration changed an existing environment's store schema"
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT count(*) FROM store_objects "
            "WHERE vault_binding_id = 'binding-a' AND object_id = %s",
            (object_id,),
        ).fetchone()
        assert row is not None and row[0] == 1, "Migration moved/destroyed existing data"


def test_store_and_child_binding_shapes_match_migration_and_autocreate(
    scratch_db_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final Alembic shape equals audited store autocreate plus child migration."""
    migrated = scratch_db_factory()
    bootstrapped = scratch_db_factory()
    _alembic_upgrade(migrated, monkeypatch, STORE_BINDING_HEAD)
    _run_ensure_tables(bootstrapped, monkeypatch)

    migrated_store_shape = _schema_snapshot(migrated)
    bootstrapped_store_shape = _schema_snapshot(bootstrapped)
    assert migrated_store_shape == bootstrapped_store_shape, (
        "MVR-05A3 Alembic/autocreate binding shape diverged:\n"
        f"alembic: {json.dumps(migrated_store_shape, indent=2, default=str)}\n"
        f"autocreate: {json.dumps(bootstrapped_store_shape, indent=2, default=str)}"
    )
    migrated_shape = _binding_shape_snapshot(migrated)
    bootstrapped_shape = _binding_shape_snapshot(bootstrapped)
    assert _minimum_child_binding_shape(migrated_shape) == _minimum_child_binding_shape(
        bootstrapped_shape
    ), (
        "MVR-05A4 child binding/key/FK autocreate parity diverged:\n"
        f"alembic: {json.dumps(_minimum_child_binding_shape(migrated_shape), indent=2, default=str)}\n"
        f"autocreate: {json.dumps(_minimum_child_binding_shape(bootstrapped_shape), indent=2, default=str)}"
    )
    for table in STORE_TABLES:
        assert migrated_shape[table]["pk"][0] == "vault_binding_id", table
    for table in MINIMUM_CHILD_TABLES:
        columns = {row[0] for row in migrated_shape[table]["columns"]}
        assert "vault_binding_id" in columns, table
        canonical_fks = [fk for fk in migrated_shape[table]["fks"] if fk[2] == "store_objects"]
        assert canonical_fks, f"{table} has no composite store_objects FK"
        for fk in canonical_fks:
            assert fk[1][0] == "vault_binding_id", (table, fk)
            assert fk[3] == ["vault_binding_id", "object_id"], (table, fk)
