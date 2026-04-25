from __future__ import annotations

import json
from pathlib import Path

from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord
from app.dispatcher.store import SqliteStore


def _event(**overrides) -> EventRecord:
    base = dict(
        event_id="evt-1",
        timestamp="2026-04-25T10:00:00Z",
        task_id="task-1",
        event_type="task.discovered",
        actor="agent-a",
    )
    base.update(overrides)
    return EventRecord(**base)


def test_jsonl_writer_appends_one_object_per_line(tmp_path: Path) -> None:
    target = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(target)

    writer.append(_event())
    writer.append(
        _event(
            event_id="evt-2",
            event_type="task.claimed",
            lease_id="lease-1",
            payload={"resource": "issue:622"},
        )
    )

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["event_id"] == "evt-1"
    assert parsed[1]["event_type"] == "task.claimed"
    assert parsed[1]["payload"] == {"resource": "issue:622"}


def test_jsonl_writer_creates_parent_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "events.jsonl"
    JsonlEventWriter(target).append(_event())
    assert target.exists()


def test_store_appends_to_jsonl_and_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "d.sqlite3"
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(events_path)
    store = SqliteStore(db, writer)
    store.initialize()

    store.append_event(_event())
    store.append_event(_event(event_id="evt-2", event_type="task.completed",
                              timestamp="2026-04-25T10:00:01Z"))

    sqlite_rows = store.list_events()
    jsonl_rows = writer.read_all()

    assert [r.event_id for r in sqlite_rows] == ["evt-1", "evt-2"]
    assert [r["event_id"] for r in jsonl_rows] == ["evt-1", "evt-2"]
    # JSONL audit trail and SQLite current-state are correlation-friendly
    assert {r.event_id for r in sqlite_rows} == {r["event_id"] for r in jsonl_rows}
