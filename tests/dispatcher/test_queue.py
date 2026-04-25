"""Tests for dispatcher queue selection and blocking."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import TaskRecord
from app.dispatcher.queue import block, next, unblock
from app.dispatcher.store import SqliteStore


def _task(**overrides) -> TaskRecord:
    base = dict(
        task_id="task-1",
        issue_number=623,
        title="Test task",
        status="ready",
        priority="high",
        source_anchor_refs=["#617"],
        created_at="2026-04-25T10:00:00Z",
        updated_at="2026-04-25T10:00:00Z",
    )
    base.update(overrides)
    return TaskRecord(**base)


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    db = tmp_path / "dispatcher.sqlite3"
    events = tmp_path / "events.jsonl"
    s = SqliteStore(db, JsonlEventWriter(events))
    s.initialize()
    return s


def test_next_returns_ready_unblocked_unleased(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    result = next(store, agent_id="test-agent")
    assert result is not None
    assert result.task_id == "task-1"


def test_next_excludes_blocked_tasks(store: SqliteStore) -> None:
    task = _task(blocked_reason="waiting for feedback")
    store.upsert_task(task)

    result = next(store, agent_id="test-agent")
    assert result is None


def test_next_excludes_claimed_tasks(store: SqliteStore) -> None:
    task = _task(lease_id="lease-1", claimed_by="other-agent")
    store.upsert_task(task)

    result = next(store, agent_id="test-agent")
    assert result is None


def test_next_excludes_non_ready_tasks(store: SqliteStore) -> None:
    task = _task(status="completed")
    store.upsert_task(task)

    result = next(store, agent_id="test-agent")
    assert result is None


def test_queue_ordering_priority_then_age(store: SqliteStore) -> None:
    from app.dispatcher.leases import claim

    store.upsert_task(_task(
        task_id="low-old",
        issue_number=1,
        priority="low",
        created_at="2026-04-25T08:00:00Z",
        updated_at="2026-04-25T08:00:00Z",
    ))
    store.upsert_task(_task(
        task_id="high-new",
        issue_number=2,
        priority="high",
        created_at="2026-04-25T11:00:00Z",
        updated_at="2026-04-25T11:00:00Z",
    ))
    store.upsert_task(_task(
        task_id="high-old",
        issue_number=3,
        priority="high",
        created_at="2026-04-25T09:00:00Z",
        updated_at="2026-04-25T09:00:00Z",
    ))

    first = next(store, "agent")
    assert first.task_id == "high-old"
    claim(store, first.task_id, "agent-1")

    second = next(store, "agent")
    assert second.task_id == "high-new"
    claim(store, second.task_id, "agent-1")

    third = next(store, "agent")
    assert third.task_id == "low-old"


def test_block_marks_blocked(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    blocked_task = block(store, "task-1", "waiting for dependency", "agent-1")

    assert blocked_task.blocked_reason == "waiting for dependency"
    assert blocked_task.updated_at != task.updated_at

    events = store.list_events("task-1")
    assert len(events) == 1
    assert events[0].event_type == "task.blocked"
    assert events[0].payload["reason"] == "waiting for dependency"


def test_blocked_excluded_from_next(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    block(store, "task-1", "waiting", "agent-1")

    result = next(store, "agent-2")
    assert result is None


def test_unblock_clears_reason(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    block(store, "task-1", "waiting", "agent-1")

    unblocked = unblock(store, "task-1", "agent-1")
    assert unblocked.blocked_reason is None
    assert unblocked.status == "ready"

    result = next(store, "agent-2")
    assert result is not None


def test_block_emits_event(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    block(store, "task-1", "blocked reason", "blocker-agent")

    events = store.list_events()
    assert len(events) == 1
    assert events[0].event_type == "task.blocked"
    assert events[0].actor == "blocker-agent"
    assert events[0].payload["reason"] == "blocked reason"


def test_multiple_ready_tasks_returns_in_order(store: SqliteStore) -> None:
    from app.dispatcher.leases import claim

    for i in range(3):
        store.upsert_task(_task(
            task_id=f"task-{i}",
            issue_number=100 + i,
            priority="high",
            created_at=f"2026-04-25T{10+i:02d}:00:00Z",
            updated_at=f"2026-04-25T{10+i:02d}:00:00Z",
        ))

    result1 = next(store, "agent")
    assert result1.task_id == "task-0"
    claim(store, result1.task_id, "agent-1")

    result2 = next(store, "agent")
    assert result2.task_id == "task-1"
    claim(store, result2.task_id, "agent-1")

    result3 = next(store, "agent")
    assert result3.task_id == "task-2"
