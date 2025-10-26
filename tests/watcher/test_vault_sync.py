import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from app.agent.events import INGEST_OBJECT_CREATED
from app.services.outbox import bootstrap
from app.services.vault_sync import handle_rename, sync_markdown


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")
    return url.replace("postgresql+psycopg://", "postgresql://")


def _reset_db() -> None:
    bootstrap()
    with psycopg.connect(_dsn(), row_factory=dict_row, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "create table if not exists file_state (path text primary key, uuid text, fm_hash text, body_hash text, mtime timestamptz, last_seen timestamptz default now())"
            )
            cur.execute("delete from outbox")
            cur.execute("delete from file_state")
            cur.execute("delete from objects")


def _outbox_topics() -> list[str]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("select topic from outbox order by id asc")
        return [row["topic"] for row in cur.fetchall()]


def _object_path(uuid_value: str) -> str | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("select path from objects where uuid=%s", (uuid_value,))
        row = cur.fetchone()
    return row["path"] if row else None


def test_rename_updates_path_without_reembed(tmp_path: Path) -> None:
    _reset_db()
    note_uuid = str(uuid4())
    original = tmp_path / "original.md"
    original.write_text(f"---\nuuid: {note_uuid}\n---\n\nBody", encoding="utf-8")
    sync_markdown(str(original))
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("delete from outbox")
    old_path = str(original)
    renamed = tmp_path / "renamed.md"
    original.rename(renamed)
    handle_rename(old_path, str(renamed))
    assert _object_path(note_uuid) == str(renamed)
    assert _outbox_topics() == []


def test_body_change_triggers_reembed(tmp_path: Path) -> None:
    _reset_db()
    note_uuid = str(uuid4())
    note = tmp_path / "note.md"
    note.write_text(f"---\nuuid: {note_uuid}\n---\n\nBody", encoding="utf-8")
    sync_markdown(str(note))
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("delete from outbox")
    note.write_text(f"---\nuuid: {note_uuid}\n---\n\nBody updated", encoding="utf-8")
    result = sync_markdown(str(note))
    assert result["reembedded"] is True
    topics = _outbox_topics()
    assert "ingest.object.updated" in topics


def test_new_note_injects_uuid_and_queues_ingest(tmp_path: Path) -> None:
    _reset_db()
    note = tmp_path / "new.md"
    note.write_text("Fresh body", encoding="utf-8")
    result = sync_markdown(str(note))
    content = note.read_text(encoding="utf-8")
    assert content.startswith("---\n") and "uuid:" in content
    topics = _outbox_topics()
    assert topics and topics[0] == INGEST_OBJECT_CREATED
    assert result["uuid"] is not None


def test_active_edit_appends_inbox(tmp_path: Path) -> None:
    _reset_db()
    inbox = Path("Inbox/System-changes.md")
    if inbox.exists():
        inbox.unlink()
    note = tmp_path / "active.md"
    note.write_text("---\nuuid: %s\n---\n\nBody" % uuid4(), encoding="utf-8")
    os.utime(note, None)
    result = sync_markdown(str(note))
    assert result["status"] == "deferred"
    assert inbox.exists()
    assert "Skipped sync" in inbox.read_text(encoding="utf-8")
    assert _outbox_topics() == []
