"""MVR-05A0 (#4543): no `file_state` write in vault_sync can reach another binding.

Three statements crossed bindings before this slice, all in
`app/services/vault_sync.py`:

* the rename cleanup in `_update_path_only` — `delete from file_state where
  uuid = %s and path <> %s`, keyed on the frontmatter UUID alone, which the same
  note copied into two vaults shares;
* the identical statement in `update_path`;
* the delete in `delete_note` — `delete from file_state where path = %s`, which
  was safe only while `path` was the primary key and stops being safe the moment
  two bindings can hold one path. Its companion `select count(*) from file_state
  where uuid = %s` had the same problem in the other direction: binding A's
  surviving row would suppress binding B's deletion tombstone.

These tests drive the **production entrypoints** against a real migrated
Postgres with a foreign binding's rows present, so they exercise the shipped SQL
rather than a stub. `#4543` requires these to be scoped, not documented — a
comment is not a fix.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]

FOREIGN_BINDING = "binding-99999999-9999-4999-8999-999999999999"
NOTE_UUID = str(uuid.UUID(int=42))


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def vault_sync_db(monkeypatch: pytest.MonkeyPatch):
    """Throwaway migrated database wired into `vault_sync`'s real connection path."""
    from alembic import command
    from alembic.config import Config

    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_bindingscope_{uuid.uuid4().hex[:12]}"
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

    # `conn_rw` caches "schema already applied" per process, and the store layer
    # caches "tables ready"; both must forget the previous test's database.
    from app.db import db as db_module
    from app.stores import pg as pg_store

    monkeypatch.setattr(db_module, "_SCHEMA_INITIALIZED", False)
    monkeypatch.setattr(pg_store, "_TABLES_READY", False)

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _seed(dsn: str, binding_id: str, path: str, note_uuid: str = NOTE_UUID) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO public.file_state
                (vault_binding_id, path, uuid, fm_hash, body_hash, mtime, last_seen)
            VALUES (%s, %s, %s, 'fm', 'body', %s, now())
            ON CONFLICT (vault_binding_id, path) DO NOTHING
            """,
            (binding_id, path, note_uuid, datetime(2026, 7, 1, tzinfo=timezone.utc)),
        )


def _rows(dsn: str) -> set[tuple[str, str]]:
    with psycopg.connect(dsn) as conn:
        return {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT vault_binding_id, path FROM public.file_state"
            ).fetchall()
        }


def test_uuid_delete_cannot_cross_bindings(vault_sync_db: str, tmp_path: Path) -> None:
    """`update_path`'s rename cleanup leaves the other binding's row for that UUID."""
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID
    from app.services import vault_sync

    old_path = str((tmp_path / "old.md").resolve())
    new_path = str((tmp_path / "new.md").resolve())
    # Same note UUID, held by two bindings, at paths that differ from the rename
    # target — precisely the `uuid = %s and path <> %s` delete predicate.
    foreign_path = str((tmp_path / "foreign.md").resolve())
    _seed(vault_sync_db, FILE_STATE_COMPATIBILITY_BINDING_ID, old_path)
    _seed(vault_sync_db, FOREIGN_BINDING, foreign_path)

    assert (FOREIGN_BINDING, foreign_path) in _rows(vault_sync_db)

    vault_sync.update_path(NOTE_UUID, new_path)

    rows = _rows(vault_sync_db)
    assert (FOREIGN_BINDING, foreign_path) in rows, (
        "the UUID-keyed rename cleanup deleted another binding's row; it is "
        "still not binding-scoped"
    )
    assert (FILE_STATE_COMPATIBILITY_BINDING_ID, new_path) in rows
    assert (FILE_STATE_COMPATIBILITY_BINDING_ID, old_path) not in rows, (
        "the rename cleanup must still collapse stale paths inside its own binding"
    )


def test_path_delete_cannot_cross_bindings(vault_sync_db: str, tmp_path: Path) -> None:
    """`delete_note`'s path delete no longer removes a foreign binding's same-path row."""
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID
    from app.services import vault_sync

    shared_path = str((tmp_path / "shared.md").resolve())
    _seed(vault_sync_db, FILE_STATE_COMPATIBILITY_BINDING_ID, shared_path)
    _seed(vault_sync_db, FOREIGN_BINDING, shared_path)

    vault_sync.delete_note(shared_path, uuid_value=NOTE_UUID)

    rows = _rows(vault_sync_db)
    assert (FOREIGN_BINDING, shared_path) in rows, (
        "delete_note removed another binding's row for the same path; `path` "
        "alone stopped being unique when the key became (vault_binding_id, path)"
    )
    assert (FILE_STATE_COMPATIBILITY_BINDING_ID, shared_path) not in rows


def test_foreign_binding_row_cannot_suppress_the_deletion_tombstone(
    vault_sync_db: str, tmp_path: Path
) -> None:
    """The last-remaining-path count is binding-scoped, so B's row is not A's business."""
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID
    from app.services import vault_sync

    own_path = str((tmp_path / "own.md").resolve())
    foreign_path = str((tmp_path / "other-vault" / "own.md").resolve())
    _seed(vault_sync_db, FILE_STATE_COMPATIBILITY_BINDING_ID, own_path)
    _seed(vault_sync_db, FOREIGN_BINDING, foreign_path)

    emitted = vault_sync.delete_note(own_path, uuid_value=NOTE_UUID)

    assert emitted is True, (
        "an unscoped `select count(*) ... where uuid = %s` counts the other "
        "binding's row as a remaining path and silently swallows the deletion "
        "tombstone for this binding"
    )
    with psycopg.connect(vault_sync_db) as conn:
        topics = [
            row[0]
            for row in conn.execute("SELECT topic FROM public.outbox ORDER BY created_at").fetchall()
        ]
    assert "ingest.object.deleted" in topics, topics


def test_reads_do_not_resolve_another_bindings_row(vault_sync_db: str, tmp_path: Path) -> None:
    """`_get_state_by_path`/`_get_state_by_uuid` are scoped, not just the writes.

    An unscoped read is the same defect one step earlier: it would let this
    binding treat another binding's sync state as its own and skip a real resync.
    """
    from app.db.db import FILE_STATE_COMPATIBILITY_BINDING_ID
    from app.services import vault_sync

    foreign_only = str((tmp_path / "foreign-only.md").resolve())
    _seed(vault_sync_db, FOREIGN_BINDING, foreign_only)

    with psycopg.connect(vault_sync_db, row_factory=psycopg.rows.dict_row) as conn:
        by_path = vault_sync._get_state_by_path(
            conn, foreign_only, binding_id=FILE_STATE_COMPATIBILITY_BINDING_ID
        )
        by_uuid = vault_sync._get_state_by_uuid(
            conn, NOTE_UUID, binding_id=FILE_STATE_COMPATIBILITY_BINDING_ID
        )
        foreign_view = vault_sync._get_state_by_path(
            conn, foreign_only, binding_id=FOREIGN_BINDING
        )

    assert by_path is None
    assert by_uuid is None
    assert foreign_view is not None and foreign_view["path"] == foreign_only
