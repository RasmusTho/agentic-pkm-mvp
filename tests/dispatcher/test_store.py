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


def _write_legacy_v1_db(db_path: Path) -> None:
    """Create a pre-multi-repo (schema v1) dispatcher DB with one legacy row."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE dispatcher_tasks (
            task_id TEXT PRIMARY KEY,
            issue_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            source_anchor_refs TEXT NOT NULL,
            claimed_by TEXT,
            lease_id TEXT,
            lease_expires_at TEXT,
            linked_pr TEXT,
            blocked_reason TEXT,
            last_heartbeat_at TEXT,
            sync_state TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE TABLE dispatcher_events (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, "
        "task_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL, "
        "lease_id TEXT, payload TEXT)"
    )
    conn.execute(
        "INSERT INTO dispatcher_tasks (task_id, issue_number, title, status, priority, "
        "source_anchor_refs, created_at, updated_at) VALUES "
        "('github-issue-101', 101, 'Legacy task', 'ready', 'high', '[]', 'x', 'x')"
    )
    conn.execute(
        "INSERT INTO dispatcher_events (event_id, timestamp, task_id, event_type, actor) "
        "VALUES ('evt-legacy', 'x', 'github-issue-101', 'task.discovered', 'agent-a')"
    )
    conn.commit()
    conn.close()


def test_legacy_v1_db_self_heals_without_reinitialize(tmp_path: Path) -> None:
    """A pre-multi-repo DB whose ``dispatcher tasks`` never re-runs ``init``
    (e.g. a long-lived shared instance) must still pick up the ``repo``
    column and repo-qualified task_id the first time anything touches it —
    not only when ``initialize()`` happens to run again.
    """
    db_path = tmp_path / "legacy.sqlite3"
    _write_legacy_v1_db(db_path)

    # No .initialize() call — mirrors a shared instance whose DB already
    # existed before this migration shipped and is never re-init'ed.
    store = SqliteStore(db_path, JsonlEventWriter(tmp_path / "events.jsonl"))
    migrated = store.get_task("github-RasmusTho--agentic-pkm-mvp-issue-101")

    assert migrated is not None
    assert migrated.title == "Legacy task"
    assert migrated.repo == "RasmusTho/agentic-pkm-mvp"
    assert store.get_task("github-issue-101") is None

    events = store.list_events("github-RasmusTho--agentic-pkm-mvp-issue-101")
    assert [e.event_id for e in events] == ["evt-legacy"]


def test_concurrent_legacy_migration_does_not_raise_or_corrupt(tmp_path: Path) -> None:
    """Two processes touching the same never-reinitialized legacy DB at once
    must not crash on ``duplicate column name`` or leave the migration half
    applied — the ``BEGIN IMMEDIATE`` + re-check-under-lock in
    ``_ensure_schema`` must serialize them safely instead.
    """
    import threading

    db_path = tmp_path / "legacy.sqlite3"
    _write_legacy_v1_db(db_path)

    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def touch() -> None:
        try:
            barrier.wait(timeout=5)
            store = SqliteStore(db_path, JsonlEventWriter(tmp_path / "events.jsonl"))
            store.get_task("github-RasmusTho--agentic-pkm-mvp-issue-101")
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=touch) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], f"concurrent migration raised: {errors!r}"

    store = SqliteStore(db_path, JsonlEventWriter(tmp_path / "events.jsonl"))
    migrated = store.get_task("github-RasmusTho--agentic-pkm-mvp-issue-101")
    assert migrated is not None
    assert migrated.repo == "RasmusTho/agentic-pkm-mvp"
    assert store.get_task("github-issue-101") is None
    # No duplicate rows from a half-serialized migration.
    assert len(store.list_tasks(repo="RasmusTho/agentic-pkm-mvp")) == 1
