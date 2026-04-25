from __future__ import annotations

from pathlib import Path

import pytest

from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.schema import SCHEMA_VERSION
from app.dispatcher.store import SqliteStore


def _task(**overrides) -> TaskRecord:
    base = dict(
        task_id="task-1",
        issue_number=622,
        title="Implement dispatcher store",
        status="ready",
        priority="high",
        source_anchor_refs=["#617", "#621"],
        created_at="2026-04-25T10:00:00Z",
        updated_at="2026-04-25T10:00:00Z",
    )
    base.update(overrides)
    return TaskRecord(**base)


def _lease(**overrides) -> LeaseRecord:
    base = dict(
        lease_id="lease-1",
        resource="issue:622",
        holder="agent-a",
        ttl_seconds=300,
        acquired_at="2026-04-25T10:00:00Z",
        expires_at="2026-04-25T10:05:00Z",
    )
    base.update(overrides)
    return LeaseRecord(**base)


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


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    db = tmp_path / "dispatcher.sqlite3"
    events = tmp_path / "events.jsonl"
    s = SqliteStore(db, JsonlEventWriter(events))
    s.initialize()
    return s


def test_initialize_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "d.sqlite3"
    store = SqliteStore(db)
    store.initialize()
    assert db.exists()
    # second init must be idempotent
    store.initialize()
    import sqlite3

    with sqlite3.connect(db) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "dispatcher_tasks",
            "dispatcher_leases",
            "dispatcher_events",
            "dispatcher_meta",
        } <= names
        version = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == str(SCHEMA_VERSION)


def test_task_round_trip(store: SqliteStore) -> None:
    task = _task(
        sync_state={"sync_result": "ok", "source_version": "etag-1"},
        linked_pr="PR-1",
    )
    store.upsert_task(task)
    fetched = store.get_task(task.task_id)
    assert fetched == task


def test_task_upsert_updates_required_fields(store: SqliteStore) -> None:
    store.upsert_task(_task())
    store.upsert_task(
        _task(status="in_progress", claimed_by="agent-a", lease_id="lease-1",
              lease_expires_at="2026-04-25T10:05:00Z",
              updated_at="2026-04-25T10:01:00Z")
    )
    t = store.get_task("task-1")
    assert t is not None
    assert t.status == "in_progress"
    assert t.claimed_by == "agent-a"
    assert t.lease_id == "lease-1"


def test_lease_round_trip(store: SqliteStore) -> None:
    lease = _lease(heartbeat_at="2026-04-25T10:02:00Z")
    store.upsert_lease(lease)
    assert store.get_lease(lease.lease_id) == lease


def test_event_persistence_in_sqlite(store: SqliteStore) -> None:
    e1 = _event()
    e2 = _event(event_id="evt-2", event_type="task.claimed", lease_id="lease-1",
                payload={"resource": "issue:622"},
                timestamp="2026-04-25T10:00:01Z")
    store.append_event(e1)
    store.append_event(e2)

    rows = store.list_events()
    assert [r.event_id for r in rows] == ["evt-1", "evt-2"]
    assert rows[1].payload == {"resource": "issue:622"}
    assert rows[1].lease_id == "lease-1"

    only_task = store.list_events(task_id="task-1")
    assert len(only_task) == 2


def test_missing_records_return_none(store: SqliteStore) -> None:
    assert store.get_task("missing") is None
    assert store.get_lease("missing") is None


def test_load_paths_env_overrides(tmp_path: Path) -> None:
    env = {
        "DISPATCHER_STATE_DIR": str(tmp_path / "state"),
        "DISPATCHER_DB_PATH": str(tmp_path / "custom.sqlite3"),
        "DISPATCHER_EVENTS_PATH": str(tmp_path / "custom.jsonl"),
    }
    paths = load_paths(env)
    assert paths.state_dir == tmp_path / "state"
    assert paths.db_path == tmp_path / "custom.sqlite3"
    assert paths.events_path == tmp_path / "custom.jsonl"
    paths.ensure()
    assert paths.state_dir.is_dir()


def test_load_paths_defaults_under_state_dir(tmp_path: Path) -> None:
    env = {"DISPATCHER_STATE_DIR": str(tmp_path / "rt")}
    paths = load_paths(env)
    assert paths.db_path == tmp_path / "rt" / "dispatcher.sqlite3"
    assert paths.events_path == tmp_path / "rt" / "events.jsonl"
