"""Lease and claim management for the dispatcher MVP."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

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
    takeover_stale: bool = False,
) -> tuple[TaskRecord, LeaseRecord]:
    """Claim a task by creating a lease and updating task state.

    Atomically within a single transaction:
    1. Check if task is ready and unleased, or explicitly take over an expired lease
    2. Create lease
    3. Update task with lease reference and claimed_by
    4. Emit task.claimed event

    Raises ValueError if task doesn't exist, is not ready, or is already claimed.
    """
    lease_id = _make_lease_id()
    ttl_seconds = ttl_minutes * 60
    now = _utc_now()
    expires = _expires_at(ttl_seconds)
    event_payload: dict[str, object] = {"ttl_minutes": ttl_minutes}

    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task_row = conn.execute(
            "SELECT * FROM dispatcher_tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if task_row is None:
            raise ValueError(f"Task {task_id} not found")

        existing_lease_id = task_row["lease_id"]
        if existing_lease_id is not None:
            existing_lease = conn.execute(
                "SELECT * FROM dispatcher_leases WHERE lease_id = ?",
                (existing_lease_id,),
            ).fetchone()
            if existing_lease is None:
                raise ValueError(f"Cannot claim task {task_id}: already has active lease")

            is_expired = (
                existing_lease["released_at"] is None
                and _parse_rfc3339(existing_lease["expires_at"]) <= _parse_rfc3339(now)
            )
            if not is_expired:
                raise ValueError(f"Cannot claim task {task_id}: already has active lease")
            if not takeover_stale:
                raise ValueError(
                    f"Cannot claim task {task_id}: lease has expired; retry with --takeover-stale"
                )
            if task_row["status"] not in {"claimed", "ready"}:
                raise ValueError(
                    f"Cannot claim task {task_id}: not eligible for stale takeover "
                    f"(current: {task_row['status']})"
                )

            result = conn.execute(
                """
                UPDATE dispatcher_leases
                SET released_at = ?, release_reason = 'stale_takeover'
                WHERE lease_id = ? AND released_at IS NULL
                """,
                (now, existing_lease_id),
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"Cannot claim task {task_id}: preconditions changed (concurrent lease update)"
                )
            event_payload["takeover"] = {
                "previous_holder": existing_lease["holder"],
                "previous_lease_id": existing_lease_id,
                "previous_expires_at": existing_lease["expires_at"],
            }
        elif task_row["status"] != "ready":
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

        result = conn.execute(
            """
            UPDATE dispatcher_tasks
            SET lease_id = ?, claimed_by = ?, lease_expires_at = ?, status = 'claimed', updated_at = ?
            WHERE task_id = ?
              AND status = ?
              AND lease_id IS ?
            """,
            (
                lease_id,
                agent_id,
                expires,
                now,
                task_id,
                task_row["status"],
                existing_lease_id,
            )
        )

        if result.rowcount == 0:
            raise ValueError(f"Cannot claim task {task_id}: preconditions changed (concurrent claim or status change)")

        event = EventRecord(
            event_id=_make_event_id(),
            timestamp=now,
            task_id=task_id,
            event_type="task.claimed",
            actor=agent_id,
            lease_id=lease_id,
            payload=event_payload,
        )
        conn.execute(
            """
            INSERT INTO dispatcher_events (
                event_id, timestamp, task_id, event_type, actor, lease_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.timestamp,
                event.task_id,
                event.event_type,
                event.actor,
                event.lease_id,
                json.dumps(event.payload, sort_keys=True, ensure_ascii=False),
            ),
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
    assert task is not None, f"task {task_id} missing after successful claim"

    if store._event_writer is not None:
        store._event_writer.append(event)

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
    now = _utc_now()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM dispatcher_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task["lease_id"] is None:
            raise ValueError(f"Task {task_id} has no active lease")
        lease = conn.execute("SELECT * FROM dispatcher_leases WHERE lease_id = ?", (task["lease_id"],)).fetchone()
        if lease is None:
            raise ValueError(f"Lease {task['lease_id']} not found")
        if lease["holder"] != agent_id:
            raise ValueError(
                f"Cannot heartbeat lease {task['lease_id']}: held by {lease['holder']}, not {agent_id}"
            )
        if lease["released_at"] is not None or _parse_rfc3339(lease["expires_at"]) <= _parse_rfc3339(now):
            raise ValueError(f"Cannot heartbeat lease {task['lease_id']}: lease has expired")
        expires = _expires_at(lease["ttl_seconds"])
        updated = conn.execute(
            "UPDATE dispatcher_leases SET heartbeat_at = ?, expires_at = ? WHERE lease_id = ? AND holder = ? AND released_at IS NULL AND expires_at > ?",
            (now, expires, lease["lease_id"], agent_id, now),
        )
        if updated.rowcount != 1:
            raise ValueError(f"Cannot heartbeat lease {task['lease_id']}: lease changed concurrently")
        updated = conn.execute(
            "UPDATE dispatcher_tasks SET last_heartbeat_at = ?, lease_expires_at = ?, updated_at = ? WHERE task_id = ? AND lease_id = ? AND claimed_by = ?",
            (now, expires, now, task_id, lease["lease_id"], agent_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"Cannot heartbeat lease {task['lease_id']}: task changed concurrently")
        event = EventRecord(_make_event_id(), now, task_id, "task.heartbeat", agent_id, lease["lease_id"])
        conn.execute("INSERT INTO dispatcher_events (event_id, timestamp, task_id, event_type, actor, lease_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?)", (event.event_id, event.timestamp, event.task_id, event.event_type, event.actor, event.lease_id, None))
        conn.commit()
    if store._event_writer is not None:
        store._event_writer.append(event)
    return LeaseRecord(lease["lease_id"], lease["resource"], agent_id, lease["ttl_seconds"], lease["acquired_at"], expires, now)


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

    Reclaims expired leases with audit trail attribution to the specified actor.

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
        lease_id = row["lease_id"]
        try:
            task = store.get_task(task_id)
            lease = store.get_lease(lease_id)

            if task is None or lease is None:
                continue

            lease.released_at = now
            lease.release_reason = "expired"
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
                actor=actor,
                lease_id=lease_id,
                payload={"reason": "expired"},
            )
            store.append_event(event)

            reclaimed.append(task_id)
        except (ValueError, Exception):
            pass

    return reclaimed
