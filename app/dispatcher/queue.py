"""Queue selection and task blocking for the dispatcher MVP."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from app.dispatcher.models import EventRecord, TaskRecord
from app.dispatcher.store import SqliteStore


def _utc_now() -> str:
    """Return current UTC timestamp in RFC3339 format."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_event_id() -> str:
    """Generate a unique event ID."""
    return f"evt-{uuid.uuid4().hex[:8]}"


def next(store: SqliteStore, agent_id: str) -> TaskRecord | None:
    """Return the next ready, unblocked, unleased task.

    Tasks are ordered by priority first, then by creation/update time (age).
    """
    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM dispatcher_tasks
            WHERE status = 'ready'
              AND blocked_reason IS NULL
              AND lease_id IS NULL
            ORDER BY
              CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'med' THEN 2
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
              END,
              updated_at ASC,
              created_at ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    return _row_to_task(row)


def block(
    store: SqliteStore,
    task_id: str,
    reason: str,
    actor: str,
) -> TaskRecord:
    """Mark a task as blocked with an explicit reason.

    Emits a task.blocked event.
    """
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    task.blocked_reason = reason
    task.status = "blocked"
    task.updated_at = _utc_now()
    store.upsert_task(task)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=_utc_now(),
        task_id=task_id,
        event_type="task.blocked",
        actor=actor,
        payload={"reason": reason},
    )
    store.append_event(event)

    return task


def unblock(
    store: SqliteStore,
    task_id: str,
    actor: str,
) -> TaskRecord:
    """Clear the blocked_reason and return task to ready (if not also leased/claimed)."""
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    task.blocked_reason = None
    task.updated_at = _utc_now()

    if task.status == "blocked":
        task.status = "ready"

    store.upsert_task(task)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=_utc_now(),
        task_id=task_id,
        event_type="task.updated",
        actor=actor,
        payload={"action": "unblocked"},
    )
    store.append_event(event)

    return task


def complete(
    store: SqliteStore,
    task_id: str,
    actor: str,
) -> TaskRecord:
    """Mark a task as completed, releasing its lease.

    Only the current lease holder can complete the task.
    Emits a task.completed event.
    """
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.lease_id is None:
        raise ValueError(f"Task {task_id} has no active lease")

    lease = store.get_lease(task.lease_id)
    if lease is None:
        raise ValueError(f"Lease {task.lease_id} not found")

    if lease.holder != actor:
        raise ValueError(
            f"Cannot complete task {task_id}: held by {lease.holder}, not {actor}"
        )

    now = _utc_now()
    lease.released_at = now
    lease.release_reason = "completed"
    store.upsert_lease(lease)

    task.status = "completed"
    task.lease_id = None
    task.claimed_by = None
    task.last_heartbeat_at = None
    task.updated_at = now
    store.upsert_task(task)

    event = EventRecord(
        event_id=_make_event_id(),
        timestamp=now,
        task_id=task_id,
        event_type="task.completed",
        actor=actor,
        lease_id=lease.lease_id,
    )
    store.append_event(event)

    return task


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    """Convert a sqlite3.Row to a TaskRecord."""
    import json

    def _loads(value: str | None) -> Any:
        if value is None or value == "":
            return None
        return json.loads(value)

    return TaskRecord(
        task_id=row["task_id"],
        issue_number=row["issue_number"],
        title=row["title"],
        status=row["status"],
        priority=row["priority"],
        source_anchor_refs=list(_loads(row["source_anchor_refs"]) or []),
        claimed_by=row["claimed_by"],
        lease_id=row["lease_id"],
        lease_expires_at=row["lease_expires_at"],
        linked_pr=row["linked_pr"],
        blocked_reason=row["blocked_reason"],
        last_heartbeat_at=row["last_heartbeat_at"],
        sync_state=_loads(row["sync_state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
