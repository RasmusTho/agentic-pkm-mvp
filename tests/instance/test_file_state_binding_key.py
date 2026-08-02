"""MVR-05A0 (#4543): `file_state` admits two bindings for the same path.

`path text PRIMARY KEY` made two registered vault bindings holding the same
relative path mutually exclusive — binding B's row silently replaced binding
A's, which is exactly the overwrite MVR-05A's AC-1 forbids ("two registered
bindings ... retain independent object, file-state, vector/index, retrieval, and
receipt provenance without overwrite or cross-read").

The key is now `(vault_binding_id, path)`, where `vault_binding_id` is the
stable registry binding id
(`app/instance/vault_registry.py::VaultRegistration.vault_binding_id`).

Contract: `docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md`
`#bounded-implementation-issue-decomposition`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

BINDING_A = "binding-11111111-1111-4111-8111-111111111111"
BINDING_B = "binding-22222222-2222-4222-8222-222222222222"
SHARED_PATH = "/vault/projects/roadmap.md"


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def migrated_db(monkeypatch: pytest.MonkeyPatch) -> str:
    """A throwaway database at `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config

    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_bindingkey_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _insert(conn: psycopg.Connection, binding_id: str, path: str, body_hash: str) -> None:
    conn.execute(
        """
        INSERT INTO public.file_state
            (vault_binding_id, path, uuid, fm_hash, body_hash, mtime, last_seen)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (vault_binding_id, path) DO UPDATE SET
            body_hash = excluded.body_hash
        """,
        (
            binding_id,
            path,
            str(uuid.UUID(int=7)),
            "fm",
            body_hash,
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ),
    )


def test_two_bindings_share_a_path_without_overwrite(migrated_db: str) -> None:
    """Binding B writing the same path leaves binding A's row untouched."""
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        _insert(conn, BINDING_A, SHARED_PATH, "body-from-A")
        _insert(conn, BINDING_B, SHARED_PATH, "body-from-B")

        rows = conn.execute(
            "SELECT vault_binding_id, body_hash FROM public.file_state "
            "WHERE path = %s ORDER BY vault_binding_id",
            (SHARED_PATH,),
        ).fetchall()

    assert rows == [
        (BINDING_A, "body-from-A"),
        (BINDING_B, "body-from-B"),
    ], (
        "the second binding overwrote the first: file_state still collapses two "
        "bindings holding the same relative path"
    )


def test_the_primary_key_is_binding_scoped_not_path_scoped(migrated_db: str) -> None:
    """The rekey is structural: `path` alone carries no uniqueness any more."""
    with psycopg.connect(migrated_db) as conn:
        pk = conn.execute(
            """
            SELECT att.attname
              FROM pg_constraint con
              JOIN LATERAL unnest(con.conkey) WITH ORDINALITY key(attnum, ordinality)
                ON true
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid AND att.attnum = key.attnum
             WHERE con.conrelid = to_regclass('public.file_state')
               AND con.contype = 'p'
             ORDER BY key.ordinality
            """
        ).fetchall()
        unique_on_path_alone = conn.execute(
            """
            SELECT indexdef FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = 'file_state'
               AND indexdef ILIKE '%UNIQUE%' AND indexdef ILIKE '%(path)%'
            """
        ).fetchall()

    assert [row[0] for row in pk] == ["vault_binding_id", "path"]
    assert unique_on_path_alone == [], (
        "a leftover unique index on `path` alone would re-impose the "
        "one-binding-per-path constraint the rekey removed"
    )


def test_a_single_binding_keeps_exactly_the_old_uniqueness(migrated_db: str) -> None:
    """One binding still cannot hold two rows for one path (the reversible floor).

    Asserted with a *bare* second insert, not an upsert: an `ON CONFLICT
    (vault_binding_id, path) DO UPDATE` that updates in place is true by
    construction once the key exists and would prove nothing. The uniqueness
    claim is that the database refuses the duplicate.
    """
    from psycopg import errors

    with psycopg.connect(migrated_db, autocommit=True) as conn:
        _insert(conn, BINDING_A, SHARED_PATH, "first")

        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                "INSERT INTO public.file_state (vault_binding_id, path, uuid) VALUES (%s, %s, %s)",
                (BINDING_A, SHARED_PATH, str(uuid.UUID(int=8))),
            )

    with psycopg.connect(migrated_db, autocommit=True) as conn:
        # The upsert path still updates in place rather than duplicating.
        _insert(conn, BINDING_A, SHARED_PATH, "second")
        rows = conn.execute(
            "SELECT body_hash FROM public.file_state WHERE vault_binding_id = %s AND path = %s",
            (BINDING_A, SHARED_PATH),
        ).fetchall()

    assert rows == [("second",)], (
        "within one binding the upsert must behave exactly as the path-only key did"
    )
