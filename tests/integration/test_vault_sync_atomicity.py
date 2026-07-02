from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml
from psycopg import sql

from app.db.dsn import resolve_dsn


def _pg_base_dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_pg_base_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _dsn_with_search_path(dsn: str, schema: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _create_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))


def _drop_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def _configure_isolated_pg_test(monkeypatch) -> tuple[str, str]:
    base_dsn = _pg_base_dsn()
    schema = f"pgtest_{uuid4().hex}"
    _create_schema(base_dsn, schema)
    dsn = _dsn_with_search_path(base_dsn, schema)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    return base_dsn, schema


def _write_note(path: Path, uuid_value: str, title: str, body: str) -> None:
    frontmatter = {"uuid": uuid_value, "title": title}
    fm_dump = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    path.write_text(f"---\n{fm_dump}\n---\n\n{body}", encoding="utf-8")


def _objects_row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from objects")
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0


def _file_state_row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from file_state")
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0


def _outbox_row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from outbox")
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0


def _file_state_path_for_uuid(dsn: str, uuid_value: str) -> str | None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select path from file_state where uuid = %s", (uuid_value,))
            row = cur.fetchone()
            return row[0] if row else None


def _objects_path_for_uuid(dsn: str, uuid_value: str) -> str | None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select path from objects where uuid = %s", (uuid_value,))
            row = cur.fetchone()
            return row[0] if row else None


@pytest.mark.pg
def test_sync_markdown_all_or_nothing(tmp_path, monkeypatch) -> None:
    """Fault injection between DB statements in ``sync_markdown`` must leave zero partial rows.

    Exercises the real production entrypoint ``app.services.vault_sync.sync_markdown`` (not an
    extracted helper). A monkeypatched outbox insert raises after the objects/file_state writes
    have executed on the shared connection; because those statements now run inside one explicit
    transaction, the raise must roll back everything — no orphaned ``objects`` row, no orphaned
    ``file_state`` row, no partial ``outbox`` row.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        note_path = tmp_path / "note.md"
        uuid_value = str(uuid4())
        _write_note(note_path, uuid_value, "Atomicity Note", "hello world")

        objects_before = _objects_row_count(dsn)
        file_state_before = _file_state_row_count(dsn)
        outbox_before = _outbox_row_count(dsn)

        def _boom(*args, **kwargs):
            raise RuntimeError("injected fault: outbox insert failed")

        monkeypatch.setattr(vault_sync, "insert_object_and_outbox", _boom)

        with pytest.raises(RuntimeError, match="injected fault"):
            vault_sync.sync_markdown(str(note_path))

        # All-or-nothing: the injected failure must roll back the objects/file_state
        # writes that ran earlier in the same transaction. Zero partial rows.
        assert _objects_row_count(dsn) == objects_before
        assert _file_state_row_count(dsn) == file_state_before
        assert _outbox_row_count(dsn) == outbox_before

        # A rerun after the injected crash (fault removed) converges to fully-synced state.
        monkeypatch.undo()
        result = vault_sync.sync_markdown(str(note_path))
        assert result["status"] == "ok"
        assert _objects_row_count(dsn) == objects_before + 1
        assert _file_state_row_count(dsn) == file_state_before + 1
        assert _outbox_row_count(dsn) == outbox_before + 1
    finally:
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_sync_markdown_fault_between_file_state_and_outbox(tmp_path, monkeypatch) -> None:
    """Fault injected after the file_state write (still before outbox) is also all-or-nothing."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        note_path = tmp_path / "note2.md"
        uuid_value = str(uuid4())
        _write_note(note_path, uuid_value, "Atomicity Note 2", "body text")

        objects_before = _objects_row_count(dsn)
        file_state_before = _file_state_row_count(dsn)
        outbox_before = _outbox_row_count(dsn)

        real_enqueue = vault_sync._enqueue

        def _boom(topic, payload):
            raise RuntimeError("injected fault: enqueue failed")

        monkeypatch.setattr(vault_sync, "_enqueue", _boom)

        with pytest.raises(RuntimeError, match="injected fault"):
            vault_sync.sync_markdown(str(note_path))

        assert _objects_row_count(dsn) == objects_before
        assert _file_state_row_count(dsn) == file_state_before
        assert _outbox_row_count(dsn) == outbox_before

        monkeypatch.setattr(vault_sync, "_enqueue", real_enqueue)
        result = vault_sync.sync_markdown(str(note_path))
        assert result["status"] == "ok"
        assert _objects_row_count(dsn) == objects_before + 1
        assert _file_state_row_count(dsn) == file_state_before + 1
        assert _outbox_row_count(dsn) == outbox_before + 1
    finally:
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_rename_atomic(tmp_path, monkeypatch) -> None:
    """``handle_rename`` updates objects.path and file_state.path atomically.

    Drives the real production entrypoint ``app.services.vault_sync.handle_rename``. A fault
    injected mid-way through the underlying path update must leave both ``objects.path`` and
    ``file_state.path`` unchanged (still pointing at the old path) rather than diverging.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        old_path = tmp_path / "old.md"
        new_path = tmp_path / "new.md"
        uuid_value = str(uuid4())
        _write_note(old_path, uuid_value, "Rename Note", "content")

        # Establish baseline state at old_path via a normal sync.
        vault_sync.sync_markdown(str(old_path))
        assert _file_state_path_for_uuid(dsn, uuid_value) == str(old_path.resolve())

        # Simulate the rename on disk.
        _write_note(new_path, uuid_value, "Rename Note", "content")
        old_path.unlink()

        real_update_path_only = vault_sync._update_path_only

        def _boom(conn, **kwargs):
            raise RuntimeError("injected fault: rename update failed")

        monkeypatch.setattr(vault_sync, "_update_path_only", _boom)

        with pytest.raises(RuntimeError, match="injected fault"):
            vault_sync.handle_rename(str(old_path), str(new_path))

        # All-or-nothing: neither objects.path nor file_state.path advanced to new_path.
        assert _file_state_path_for_uuid(dsn, uuid_value) == str(old_path.resolve())
        assert _objects_path_for_uuid(dsn, uuid_value) != str(new_path.resolve())

        monkeypatch.setattr(vault_sync, "_update_path_only", real_update_path_only)
        result = vault_sync.handle_rename(str(old_path), str(new_path))
        assert result["updated"] is True
        assert _file_state_path_for_uuid(dsn, uuid_value) == str(new_path.resolve())
        assert _objects_path_for_uuid(dsn, uuid_value) == str(new_path.resolve())
    finally:
        _drop_schema(base_dsn, schema)
