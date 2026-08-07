from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml
from psycopg import sql

from app.db.dsn import resolve_dsn


def _pg_base_dsn() -> str:
    return resolve_dsn()


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


def _ensure_legacy_tables(dsn: str) -> None:
    """Guarantee ``public.objects``/``file_state``/``outbox`` exist before any
    test in this module reads or writes them.

    ``app.services.vault_sync`` only creates these tables lazily (via
    ``app.db.db.ensure_schema``) the first time a caller opens a real
    connection through ``vault_sync._conn()``. Whichever test in this module
    runs first (file collection order, not test-name order) may do its
    "before" row-count baseline read before any ``vault_sync`` call has had
    that chance, and fail with ``UndefinedTable`` on a genuinely fresh
    Postgres (#2937). Trigger schema creation explicitly up front instead of
    relying on incidental cross-test ordering.

    Since MVR-05A0 (#4543) ``file_state`` and ``objects.path`` are owned by
    Alembic revision ``c7f4b1a83d29``, not by the legacy bootstrap SQL. On a
    migrated database ``ensure_schema`` finds them already present; on a scratch
    database it supplies them through the ``STORE_SCHEMA_AUTOCREATE=1``
    test-fixture opt-in that ``tests/conftest.py`` sets for pg-marked tests.
    """
    from app.db.db import ensure_schema

    with psycopg.connect(dsn, autocommit=True) as conn:
        ensure_schema(conn)


def _configure_isolated_pg_test(monkeypatch) -> tuple[str, str]:
    base_dsn = _pg_base_dsn()
    _ensure_legacy_tables(base_dsn)
    schema = f"pgtest_{uuid4().hex}"
    _create_schema(base_dsn, schema)
    dsn = _dsn_with_search_path(base_dsn, schema)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    # Use the production store-schema producer instead of copying its DDL into
    # this test. The monkeypatched process flag is restored after each case.
    from app.stores import pg as pg_store

    monkeypatch.setattr(pg_store, "_TABLES_READY", False)
    pg_store._ensure_tables()
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


def _canonical_objects_row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from store_objects")
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0


def _canonical_payload(dsn: str, object_id: str) -> dict[str, object]:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select payload from store_objects where object_id = %s", (object_id,))
            row = cur.fetchone()
            assert row is not None
            assert isinstance(row[0], dict)
            return row[0]


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

        # A freshly-written note's mtime is always "now", so sync_markdown's
        # active_edit() grace-period check (default 5s) would otherwise defer
        # the sync and return before reaching the objects/outbox write this
        # test targets. Bypass the grace period deterministically, same
        # pattern as tests/watcher/test_fs_watcher.py.
        monkeypatch.setattr(vault_sync, "active_edit", lambda _: False)

        note_path = tmp_path / "note.md"
        uuid_value = str(uuid4())
        _write_note(note_path, uuid_value, "Atomicity Note", "hello world")

        objects_before = _objects_row_count(dsn)
        canonical_before = _canonical_objects_row_count(dsn)
        file_state_before = _file_state_row_count(dsn)
        outbox_before = _outbox_row_count(dsn)

        real_insert_object_and_outbox = vault_sync.insert_object_and_outbox

        def _boom(*args, **kwargs):
            raise RuntimeError("injected fault: outbox insert failed")

        monkeypatch.setattr(vault_sync, "insert_object_and_outbox", _boom)

        with pytest.raises(RuntimeError, match="injected fault"):
            vault_sync.sync_markdown(str(note_path))

        # All-or-nothing: the injected failure must roll back the objects/file_state
        # writes that ran earlier in the same transaction. Zero partial rows.
        assert _objects_row_count(dsn) == objects_before
        assert _canonical_objects_row_count(dsn) == canonical_before
        assert _file_state_row_count(dsn) == file_state_before
        assert _outbox_row_count(dsn) == outbox_before

        # A rerun after the injected crash (fault removed) converges to fully-synced state.
        # Restore only the fault stub, not the isolated-DSN env vars set by
        # _configure_isolated_pg_test — monkeypatch.undo() would roll those back too.
        monkeypatch.setattr(vault_sync, "insert_object_and_outbox", real_insert_object_and_outbox)
        result = vault_sync.sync_markdown(str(note_path))
        assert result["status"] == "ok"
        assert _objects_row_count(dsn) == objects_before + 1
        assert _canonical_objects_row_count(dsn) == canonical_before + 1
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

        # See test_sync_markdown_all_or_nothing: bypass the active_edit()
        # grace period so a freshly-written note's first sync reaches the
        # objects/outbox write instead of deferring.
        monkeypatch.setattr(vault_sync, "active_edit", lambda _: False)

        note_path = tmp_path / "note2.md"
        uuid_value = str(uuid4())
        _write_note(note_path, uuid_value, "Atomicity Note 2", "body text")

        objects_before = _objects_row_count(dsn)
        canonical_before = _canonical_objects_row_count(dsn)
        file_state_before = _file_state_row_count(dsn)
        outbox_before = _outbox_row_count(dsn)

        real_enqueue = vault_sync._enqueue

        def _boom(topic, payload, conn=None, **kwargs):
            raise RuntimeError("injected fault: enqueue failed")

        monkeypatch.setattr(vault_sync, "_enqueue", _boom)

        with pytest.raises(RuntimeError, match="injected fault"):
            vault_sync.sync_markdown(str(note_path))

        assert _objects_row_count(dsn) == objects_before
        assert _canonical_objects_row_count(dsn) == canonical_before
        assert _file_state_row_count(dsn) == file_state_before
        assert _outbox_row_count(dsn) == outbox_before

        monkeypatch.setattr(vault_sync, "_enqueue", real_enqueue)
        result = vault_sync.sync_markdown(str(note_path))
        assert result["status"] == "ok"
        assert _objects_row_count(dsn) == objects_before + 1
        assert _canonical_objects_row_count(dsn) == canonical_before + 1
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


@pytest.mark.pg
def test_sync_markdown_edit_preserves_richer_canonical_payload(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        monkeypatch.setattr(vault_sync, "active_edit", lambda _: False)
        note_path = tmp_path / "metadata.md"
        uuid_value = str(uuid4())
        _write_note(note_path, uuid_value, "Metadata Note", "first body")
        vault_sync.sync_markdown(str(note_path))
        with psycopg.connect(dsn) as conn:
            conn.execute(
                """
                update store_objects
                set payload = payload || %s::jsonb
                where object_id = %s
                """,
                (
                    '{"episode_ref":"episode:1","trust":"reviewed","language":"sv","stable_id":"stable:1"}',
                    uuid_value,
                ),
            )

        _write_note(note_path, uuid_value, "Metadata Note", "edited body")
        vault_sync.sync_markdown(str(note_path))

        payload = _canonical_payload(dsn, uuid_value)
        assert payload["content"] == "edited body"
        assert payload["episode_ref"] == "episode:1"
        assert payload["trust"] == "reviewed"
        assert payload["language"] == "sv"
        assert payload["stable_id"] == "stable:1"

        # ERE-03 event surface: the enqueued outbox event must carry the same
        # post-merge binding as the canonical row, not the builder sentinel.
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "select payload from outbox order by created_at desc limit 1"
            ).fetchone()
        envelope = row[0] if not isinstance(row, dict) else row["payload"]
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        assert envelope["payload"]["episode_ref"] == "episode:1"
    finally:
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_real_episode_binding_list_survives_merge_without_type_error(
    tmp_path, monkeypatch
) -> None:
    """A frontmatter-declared list binding must pass the sentinel guard cleanly."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        monkeypatch.setattr(vault_sync, "active_edit", lambda _: False)
        note_path = tmp_path / "bound.md"
        uuid_value = str(uuid4())
        frontmatter = {
            "uuid": uuid_value,
            "title": "Bound Note",
            "episode_ref": ["episode-1a2b3c4d"],
        }
        fm_dump = yaml.safe_dump(frontmatter, sort_keys=False).strip()
        note_path.write_text(f"---\n{fm_dump}\n---\n\nbound body", encoding="utf-8")

        vault_sync.sync_markdown(str(note_path))
        note_path.write_text(f"---\n{fm_dump}\n---\n\nbound body edited", encoding="utf-8")
        vault_sync.sync_markdown(str(note_path))

        payload = _canonical_payload(dsn, uuid_value)
        assert payload["episode_ref"] == ["episode-1a2b3c4d"]
        assert payload["content"] == "bound body edited"
    finally:
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_pure_rename_preserves_richer_canonical_payload(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    base_dsn, schema = _configure_isolated_pg_test(monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    try:
        from app.services import vault_sync

        monkeypatch.setattr(vault_sync, "active_edit", lambda _: False)
        old_path = tmp_path / "before.md"
        new_path = tmp_path / "after.md"
        uuid_value = str(uuid4())
        _write_note(old_path, uuid_value, "Rename Metadata", "unchanged body")
        vault_sync.sync_markdown(str(old_path))
        with psycopg.connect(dsn) as conn:
            conn.execute(
                """
                update store_objects
                set payload = payload || %s::jsonb
                where object_id = %s
                """,
                ('{"episode_ref":"episode:2","ingest_fingerprint":"fingerprint:2"}', uuid_value),
            )

        old_path.rename(new_path)
        vault_sync.handle_rename(str(old_path), str(new_path))

        payload = _canonical_payload(dsn, uuid_value)
        assert payload["episode_ref"] == "episode:2"
        assert payload["ingest_fingerprint"] == "fingerprint:2"
        assert payload["content"] == "unchanged body"
    finally:
        _drop_schema(base_dsn, schema)
