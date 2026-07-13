"""Tests for dispatcher lease and claim lifecycle."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

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
    persisted_task = store.get_task("task-1")
    persisted_lease = store.get_lease(lease.lease_id)
    assert persisted_task is not None
    assert persisted_lease is not None
    assert persisted_task.lease_expires_at == lease.expires_at
    assert persisted_lease.expires_at == lease.expires_at


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


def _expire_lease(store: SqliteStore, lease_id: str) -> str:
    lease = store.get_lease(lease_id)
    assert lease is not None
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
        timespec="microseconds"
    )
    lease.acquired_at = past_time
    lease.expires_at = past_time
    lease.heartbeat_at = past_time
    store.upsert_lease(lease)
    return past_time


def test_claim_takeover_stale_succeeds_with_attributed_receipt(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    _, old_lease = claim(store, "task-1", "departed-agent")
    previous_expires_at = _expire_lease(store, old_lease.lease_id)

    claimed_task, lease = claim(
        store, "task-1", "replacement-agent", takeover_stale=True
    )

    assert claimed_task.lease_id == lease.lease_id
    assert claimed_task.claimed_by == "replacement-agent"
    event = store.list_events("task-1")[-1]
    assert event.event_type == "task.claimed"
    assert event.payload["takeover"] == {
        "previous_holder": "departed-agent",
        "previous_lease_id": old_lease.lease_id,
        "previous_expires_at": previous_expires_at,
    }


def test_takeover_releases_expired_lease_with_stale_takeover_reason(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    _, old_lease = claim(store, "task-1", "departed-agent")
    _expire_lease(store, old_lease.lease_id)

    claim(store, "task-1", "replacement-agent", takeover_stale=True)

    released_lease = store.get_lease(old_lease.lease_id)
    assert released_lease is not None
    assert released_lease.released_at is not None
    assert released_lease.release_reason == "stale_takeover"


def test_takeover_never_displaces_active_lease(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    claim(store, "task-1", "active-agent")

    with pytest.raises(ValueError, match="already has active lease"):
        claim(store, "task-1", "replacement-agent", takeover_stale=True)


def test_expired_lease_rejection_names_takeover_path(store: SqliteStore) -> None:
    task = _task()
    store.upsert_task(task)
    _, old_lease = claim(store, "task-1", "departed-agent")
    _expire_lease(store, old_lease.lease_id)

    with pytest.raises(ValueError, match="--takeover-stale"):
        claim(store, "task-1", "replacement-agent")


def test_takeover_rejects_expired_blocked_task_without_mutation(store: SqliteStore) -> None:
    from app.dispatcher.queue import block

    task = _task()
    store.upsert_task(task)
    _, old_lease = claim(store, "task-1", "departed-agent")
    block(store, "task-1", "waiting for dependency", "dispatcher")
    _expire_lease(store, old_lease.lease_id)

    with pytest.raises(ValueError, match="not eligible for stale takeover"):
        claim(store, "task-1", "replacement-agent", takeover_stale=True)

    unchanged_task = store.get_task("task-1")
    unchanged_lease = store.get_lease(old_lease.lease_id)
    assert unchanged_task is not None
    assert unchanged_lease is not None
    assert unchanged_task.status == "blocked"
    assert unchanged_task.lease_id == old_lease.lease_id
    assert unchanged_task.claimed_by == "departed-agent"
    assert unchanged_lease.released_at is None
    assert unchanged_lease.release_reason is None
