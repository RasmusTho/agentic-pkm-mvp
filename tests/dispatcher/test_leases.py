"""Tests for dispatcher lease and claim lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.leases import claim, heartbeat, reclaim_expired_leases, release
from app.dispatcher.models import TaskRecord
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


def test_claim_creates_active_lease(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claimed_task, lease = claim(store, "task-1", "agent-1", ttl_minutes=60)

    assert claimed_task.lease_id == lease.lease_id
    assert claimed_task.claimed_by == "agent-1"
    assert claimed_task.status == "claimed"
    assert lease.holder == "agent-1"
    assert lease.ttl_seconds == 3600


def test_duplicate_claim_rejected(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)

    with pytest.raises(ValueError, match="already has active lease"):
        claim(store, "task-1", "agent-2", ttl_minutes=60)


def test_claim_not_ready_rejected(store: SqliteStore) -> None:
    task = _task(status="blocked")
    store.upsert_task(task)

    with pytest.raises(ValueError, match="not in ready status"):
        claim(store, "task-1", "agent-1", ttl_minutes=60)


def test_claim_missing_task_rejected(store: SqliteStore) -> None:
    with pytest.raises(ValueError, match="not found"):
        claim(store, "nonexistent", "agent-1", ttl_minutes=60)


def test_heartbeat_updates_lease(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    _, lease = claim(store, "task-1", "agent-1", ttl_minutes=60)
    original_heartbeat = lease.heartbeat_at

    updated_lease = heartbeat(store, "task-1", "agent-1")

    assert updated_lease.expires_at == lease.expires_at
    assert updated_lease.heartbeat_at >= original_heartbeat


def test_heartbeat_wrong_agent_rejected(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)

    with pytest.raises(ValueError, match="held by agent-1"):
        heartbeat(store, "task-1", "agent-2")


def test_heartbeat_no_lease_rejected(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    with pytest.raises(ValueError, match="no active lease"):
        heartbeat(store, "task-1", "agent-1")


def test_release_removes_lease(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    _, lease = claim(store, "task-1", "agent-1", ttl_minutes=60)

    released_task = release(store, "task-1", "agent-1", reason="completed")

    assert released_task.lease_id is None
    assert released_task.claimed_by is None
    assert released_task.status == "ready"

    fetched_lease = store.get_lease(lease.lease_id)
    assert fetched_lease.released_at is not None


def test_release_wrong_agent_rejected(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)

    with pytest.raises(ValueError, match="held by agent-1"):
        release(store, "task-1", "agent-2")


def test_release_no_lease_rejected(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    with pytest.raises(ValueError, match="no active lease"):
        release(store, "task-1", "agent-1")


def test_release_blocked_task_stays_blocked(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)

    from app.dispatcher.queue import block
    block(store, "task-1", "waiting for review", "blocker")

    released_task = release(store, "task-1", "agent-1")

    assert released_task.status == "blocked"
    assert released_task.blocked_reason == "waiting for review"


def test_claim_emits_event(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)

    events = store.list_events("task-1")
    assert len(events) == 1
    assert events[0].event_type == "task.claimed"
    assert events[0].actor == "agent-1"


def test_heartbeat_emits_event(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)
    heartbeat(store, "task-1", "agent-1")

    events = store.list_events("task-1")
    assert len(events) == 2
    event_types = [e.event_type for e in events]
    assert "task.claimed" in event_types
    assert "task.heartbeat" in event_types


def test_release_emits_event(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)

    claim(store, "task-1", "agent-1", ttl_minutes=60)
    release(store, "task-1", "agent-1", reason="completed")

    events = store.list_events("task-1")
    assert len(events) == 2
    assert events[1].event_type == "task.released"
    assert events[1].payload["reason"] == "completed"


def test_expired_lease_reclaim(store: SqliteStore) -> None:
    from app.dispatcher.models import LeaseRecord
    from datetime import datetime, timezone, timedelta

    task = _task()
    store.upsert_task(task)

    claimed_task, lease = claim(store, "task-1", "agent-1", ttl_minutes=1)

    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="microseconds")

    old_lease = LeaseRecord(
        lease_id=lease.lease_id,
        resource=lease.resource,
        holder=lease.holder,
        ttl_seconds=lease.ttl_seconds,
        acquired_at=past_time,
        expires_at=past_time,
        heartbeat_at=past_time,
    )
    store.upsert_lease(old_lease)

    reclaimed = reclaim_expired_leases(store, actor="dispatcher")

    assert "task-1" in reclaimed

    refetched = store.get_task("task-1")
    assert refetched.lease_id is None
    assert refetched.claimed_by is None
    assert refetched.status == "ready"
