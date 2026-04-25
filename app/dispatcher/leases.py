"""Lease and claim management for the dispatcher MVP."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.store import SqliteStore


def _utc_now() -> str:
    """Return current UTC timestamp in RFC3339 format."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_lease_id() -> str:
    """Generate a unique lease ID."""
    return f"lease-{uuid.uuid4().hex[:8]}"


def _make_event_id() -> str:
    """Generate a unique event ID."""
    return f"evt-{uuid.uuid4().hex[:8]}"


def _parse_rfc3339(timestamp_str: str) -> datetime:
    """Parse RFC3339 timestamp to datetime."""
    return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))


def _expires_at(ttl_seconds: int) -> str:
    """Calculate expiry timestamp given TTL in seconds."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    return expires.isoformat(timespec="seconds")


def claim(
    store: SqliteStore,
    task_id: str,
    agent_id: str,
    ttl_minutes: int = 90,
) -> tuple[TaskRecord, LeaseRecord]:
    """Claim a task by creating a lease and updating task state.

    Atomically within a single transaction:
    1. Check if task is ready and unleased
    2. Create lease
    3. Update task with lease reference and claimed_by
    4. Emit task.claimed event

    Raises ValueError if task doesn't exist, is not ready, or is already claimed.
    """
    lease_id = _make_lease_id()
    ttl_seconds = ttl_minutes * 60
    now = _utc_now()
    expires = _expires_at(ttl_seconds)

    with store._connect() as conn:
        task_row = conn.execute(
            "SELECT * FROM dispatcher_tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if task_row is None:
            raise ValueError(f"Task {task_id} not found")

        if task_row["lease_id"] is not None:
            raise ValueError(f"Cannot claim task {task_id}: already has active lease")

        if task_row["status"] != "ready":
            raise ValueError(
                f"Cannot claim task {task_id}: not in ready status (current: {task_row['status']})"
            )

        conn.execute(
            """
            INSERT INTO dispatcher_leases (
                lease_id, resource, holder, ttl_seconds, acquired_at, expires_at, heartbeat_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lease_id, f"issue:{task_row['issue_number']}", agent_id, ttl_seconds, now, expires, now)
        )

        conn.execute(
            """
            UPDATE dispatcher_tasks
            SET lease_id = ?, claimed_by = ?, status = 'claimed', updated_at = ?
            WHERE task_id = ?
            """,
            (lease_id, agent_id, now, task_id)
        )

        conn.commit()

    lease = LeaseRecord(
        lease_id=lease_id,
        resource=f"issue:{task_row['issue_number']}",
        holder=agent_id,
        ttl_seconds=ttl_seconds,
        acquired_at=now,
        expires_at=expires,
        heartbeat_at=now,
    )

    task = store.get_task(task_id)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=now,
        task_id=task_id,
        event_type="task.claimed",
        actor=agent_id,
        lease_id=lease_id,
        payload={"ttl_minutes": ttl_minutes},
    )
    store.append_event(event)

    return task, lease


def heartbeat(
    store: SqliteStore,
    task_id: str,
    agent_id: str,
) -> LeaseRecord:
    """Update the heartbeat timestamp of an active lease.

    The lease TTL is not extended; heartbeat only updates the last-seen timestamp
    and can be used to track activity.

    Raises ValueError if task/lease not found or held by a different agent.
    """
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.lease_id is None:
        raise ValueError(f"Task {task_id} has no active lease")

    lease = store.get_lease(task.lease_id)
    if lease is None:
        raise ValueError(f"Lease {task.lease_id} not found")

    if lease.holder != agent_id:
        raise ValueError(
            f"Cannot heartbeat lease {task.lease_id}: held by {lease.holder}, not {agent_id}"
        )

    now = _utc_now()
    lease.heartbeat_at = now
    store.upsert_lease(lease)

    task.last_heartbeat_at = now
    task.updated_at = now
    store.upsert_task(task)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=now,
        task_id=task_id,
        event_type="task.heartbeat",
        actor=agent_id,
        lease_id=lease.lease_id,
    )
    store.append_event(event)

    return lease


def release(
    store: SqliteStore,
    task_id: str,
    agent_id: str,
    reason: str = "manual",
) -> TaskRecord:
    """Release a task by removing its lease.

    After release, the task returns to ready status if not blocked, or stays blocked.

    Raises ValueError if task/lease not found or held by a different agent.
    """
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.lease_id is None:
        raise ValueError(f"Task {task_id} has no active lease to release")

    lease = store.get_lease(task.lease_id)
    if lease is None:
        raise ValueError(f"Lease {task.lease_id} not found")

    if lease.holder != agent_id:
        raise ValueError(
            f"Cannot release lease {task.lease_id}: held by {lease.holder}, not {agent_id}"
        )

    now = _utc_now()
    lease.released_at = now
    lease.release_reason = reason
    store.upsert_lease(lease)

    task.lease_id = None
    task.claimed_by = None
    task.last_heartbeat_at = None

    if task.blocked_reason is None:
        task.status = "ready"
    else:
        task.status = "blocked"

    task.updated_at = now
    store.upsert_task(task)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=now,
        task_id=task_id,
        event_type="task.released",
        actor=agent_id,
        lease_id=lease.lease_id,
        payload={"reason": reason},
    )
    store.append_event(event)

    return task


def reclaim_expired_leases(
    store: SqliteStore,
    actor: str = "dispatcher-gc",
) -> list[str]:
    """Find and release all expired leases.

    Returns list of task_ids that had leases reclaimed.
    """
    now = _utc_now()

    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT t.task_id, t.lease_id, l.expires_at, l.holder
            FROM dispatcher_tasks t
            JOIN dispatcher_leases l ON t.lease_id = l.lease_id
            WHERE l.released_at IS NULL AND l.expires_at < ?
            ORDER BY l.expires_at
            """,
            (now,)
        ).fetchall()

    reclaimed = []
    for row in rows:
        task_id = row["task_id"]
        holder = row["holder"]
        try:
            release(store, task_id, holder, reason="expired")
            reclaimed.append(task_id)
        except (ValueError, Exception):
            pass

    return reclaimed
