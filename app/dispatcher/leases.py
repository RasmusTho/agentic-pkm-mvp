"""Lease and claim management for the dispatcher MVP."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.store import SqliteStore

try:
    import fcntl
except ImportError:  # pragma: no cover - dispatcher runs on POSIX hosts.
    fcntl = None  # type: ignore[assignment]


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


def _expires_at(ttl_seconds: int, *, now: str | None = None) -> str:
    """Calculate expiry timestamp given TTL in seconds."""
    current = datetime.now(timezone.utc) if now is None else _parse_rfc3339(now)
    expires = current + timedelta(seconds=ttl_seconds)
    return expires.isoformat(timespec="seconds")


_CLEANUP_GUARD_PREFIX = "cleanup-guard:task:"
_CLEANUP_GUARD_RECORD_NAME = ".dispatcher.cleanup.guard.json"
_CLEANUP_GUARD_LOCK_NAME = ".dispatcher.cleanup.guard.lock"


def _cleanup_guard_key(task_id: str) -> str:
    return f"{_CLEANUP_GUARD_PREFIX}{task_id}"


def _cleanup_guard_record_path(store: SqliteStore) -> Path:
    return store.db_path.with_name(_CLEANUP_GUARD_RECORD_NAME)


@contextmanager
def _cleanup_guard_lock(store: SqliteStore) -> Iterator[None]:
    """Serialize guard and claim operations across DB-missing transitions."""
    if fcntl is None:
        raise ValueError("cleanup guard requires POSIX file locking")
    lock_path = store.db_path.with_name(_CLEANUP_GUARD_LOCK_NAME)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _validated_cleanup_guard(value: object, task_id: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or value.get("task_id") != task_id
        or not isinstance(value.get("owner"), str)
        or not value["owner"]
        or not isinstance(value.get("token"), str)
        or not value["token"]
        or not isinstance(value.get("expires_at"), str)
    ):
        raise ValueError(f"Cleanup guard for task {task_id} is malformed")
    return {
        "task_id": task_id,
        "owner": value["owner"],
        "token": value["token"],
        "expires_at": value["expires_at"],
    }


def _read_cleanup_guard_file(
    store: SqliteStore, task_id: str, now: str
) -> dict[str, str] | None:
    path = _cleanup_guard_record_path(store)
    try:
        if path.is_symlink():
            raise ValueError(f"Cleanup guard for task {task_id} is a symlink")
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cleanup guard for task {task_id} is malformed") from exc
    guard = _validated_cleanup_guard(value, task_id)
    try:
        expired = _parse_rfc3339(guard["expires_at"]) <= _parse_rfc3339(now)
    except ValueError as exc:
        raise ValueError(f"Cleanup guard for task {task_id} has invalid expiry") from exc
    if expired:
        path.unlink()
        return None
    return guard


def _write_cleanup_guard_file(store: SqliteStore, guard: Mapping[str, str]) -> None:
    path = _cleanup_guard_record_path(store)
    if path.is_symlink():
        raise ValueError(f"Cleanup guard for task {guard['task_id']} is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(guard), sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_cleanup_guard_file(store: SqliteStore, task_id: str) -> None:
    path = _cleanup_guard_record_path(store)
    if path.is_symlink():
        raise ValueError(f"Cleanup guard for task {task_id} is a symlink")
    path.unlink(missing_ok=True)


def _read_cleanup_guard(
    conn: Any, task_id: str, now: str
) -> dict[str, str] | None:
    row = conn.execute(
        "SELECT value FROM dispatcher_meta WHERE key = ?",
        (_cleanup_guard_key(task_id),),
    ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cleanup guard for task {task_id} is malformed") from exc
    guard = _validated_cleanup_guard(value, task_id)
    try:
        expired = _parse_rfc3339(guard["expires_at"]) <= _parse_rfc3339(now)
    except ValueError as exc:
        raise ValueError(f"Cleanup guard for task {task_id} has invalid expiry") from exc
    if expired:
        conn.execute(
            "DELETE FROM dispatcher_meta WHERE key = ?",
            (_cleanup_guard_key(task_id),),
        )
        return None
    return guard


def acquire_cleanup_guard(
    store: SqliteStore,
    task_id: str,
    owner: str,
    ttl_seconds: int = 900,
) -> dict[str, str]:
    """Reserve a task resource so dispatcher claims cannot race cleanup.

    The reservation is mirrored in the existing dispatcher metadata table and
    a sidecar record, with the same file lock serializing claim/guard access
    when the database is absent. It is coordination state, not a task lease or
    lifecycle transition.
    """
    if not task_id or not owner or ttl_seconds <= 0:
        raise ValueError("Cleanup guard identity and positive TTL are required")
    token = f"guard-{uuid.uuid4().hex}"
    with _cleanup_guard_lock(store):
        now = _utc_now()
        expires = _expires_at(ttl_seconds, now=now)
        file_existing = _read_cleanup_guard_file(store, task_id, now)
        guard = {
            "task_id": task_id,
            "owner": owner,
            "token": token,
            "expires_at": expires,
        }
        if not store.db_path.exists():
            if file_existing is not None:
                if file_existing["owner"] == owner:
                    raise ValueError(
                        f"Cleanup guard for task {task_id} is already held by this invocation"
                    )
                raise ValueError(f"Cleanup guard for task {task_id} is held by another owner")
            _write_cleanup_guard_file(store, guard)
            return guard
        with store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = _read_cleanup_guard(conn, task_id, now)
            task = conn.execute(
                "SELECT status, lease_id FROM dispatcher_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is not None and (task["status"] == "claimed" or task["lease_id"] is not None):
                raise ValueError(f"Cannot acquire cleanup guard for task {task_id}: active dispatcher lease")
            for held in (file_existing, existing):
                if held is not None:
                    if held["owner"] == owner:
                        raise ValueError(
                            f"Cleanup guard for task {task_id} is already held by this invocation"
                        )
                    raise ValueError(f"Cleanup guard for task {task_id} is held by another owner")
            conn.execute(
                "INSERT INTO dispatcher_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_cleanup_guard_key(task_id), json.dumps(guard, sort_keys=True)),
            )
            conn.commit()
        _write_cleanup_guard_file(store, guard)
    return guard


def release_cleanup_guard(
    store: SqliteStore,
    task_id: str,
    owner: str,
    token: str,
) -> None:
    """Release only the exact cleanup reservation owner and token."""
    if not task_id or not owner or not token:
        raise ValueError("Cleanup guard identity is required")
    with _cleanup_guard_lock(store):
        now = _utc_now()
        file_guard = _read_cleanup_guard_file(store, task_id, now)
        db_guard = None
        if store.db_path.exists():
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                db_guard = _read_cleanup_guard(conn, task_id, now)
                guard = file_guard or db_guard
                if guard is None or guard["owner"] != owner or guard["token"] != token:
                    raise ValueError(f"Cleanup guard for task {task_id} is not held by this owner")
                if db_guard is not None:
                    deleted = conn.execute(
                        "DELETE FROM dispatcher_meta WHERE key = ?",
                        (_cleanup_guard_key(task_id),),
                    )
                    if deleted.rowcount != 1:
                        raise ValueError(f"Cleanup guard for task {task_id} changed concurrently")
                conn.commit()
        else:
            if file_guard is None or file_guard["owner"] != owner or file_guard["token"] != token:
                raise ValueError(f"Cleanup guard for task {task_id} is not held by this owner")
        _remove_cleanup_guard_file(store, task_id)


def refresh_cleanup_guard(
    store: SqliteStore,
    task_id: str,
    owner: str,
    token: str,
    ttl_seconds: int = 900,
) -> dict[str, str]:
    """Heartbeat an exact cleanup invocation without changing its identity."""
    if not task_id or not owner or not token or ttl_seconds <= 0:
        raise ValueError("Cleanup guard identity and positive TTL are required")
    with _cleanup_guard_lock(store):
        now = _utc_now()
        expires = _expires_at(ttl_seconds, now=now)
        file_guard = _read_cleanup_guard_file(store, task_id, now)
        if file_guard is None or file_guard["owner"] != owner or file_guard["token"] != token:
            raise ValueError(f"Cleanup guard for task {task_id} is not held by this owner")
        refreshed = {**file_guard, "expires_at": expires}
        if store.db_path.exists():
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                db_guard = _read_cleanup_guard(conn, task_id, now)
                if db_guard is not None and (
                    db_guard["owner"] != owner or db_guard["token"] != token
                ):
                    raise ValueError(f"Cleanup guard for task {task_id} is not held by this owner")
                if db_guard is not None:
                    updated = conn.execute(
                        "UPDATE dispatcher_meta SET value = ? WHERE key = ?",
                        (json.dumps(refreshed, sort_keys=True), _cleanup_guard_key(task_id)),
                    )
                    if updated.rowcount != 1:
                        raise ValueError(f"Cleanup guard for task {task_id} changed concurrently")
                conn.commit()
        _write_cleanup_guard_file(store, refreshed)
        return refreshed


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
    event_payload: dict[str, object] = {"ttl_minutes": ttl_minutes}

    with ExitStack() as stack:
        stack.enter_context(_cleanup_guard_lock(store))
        conn = stack.enter_context(store._connect())
        conn.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        expires = _expires_at(ttl_seconds, now=now)
        task_row = conn.execute(
            "SELECT * FROM dispatcher_tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if task_row is None:
            raise ValueError(f"Task {task_id} not found")

        if (
            _read_cleanup_guard(conn, task_id, now) is not None
            or _read_cleanup_guard_file(store, task_id, now) is not None
        ):
            raise ValueError(f"Cannot claim task {task_id}: cleanup guard is active")

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

    A heartbeat renews the active lease for its original TTL and updates the
    last-seen timestamp.

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
        # Renew only while the holder still owns an unexpired lease.  The
        # lease and task expiry updates share this transaction so a stale
        # takeover cannot observe one without the other.
        expires = _expires_at(int(lease["ttl_seconds"]), now=now)
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
    task.lease_expires_at = None

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


def _observe_expired_leases(store: SqliteStore) -> list[tuple[str, str]]:
    """Snapshot the ``(task_id, lease_id)`` pairs that currently look expired.

    This is only an *observation*: the pairs it returns may already be stale by
    the time the caller acts on them (a concurrent ``claim(..., takeover_stale=
    True)`` can release the observed lease and install a replacement). The
    authoritative expiry/ownership recheck happens later, under the write lock,
    in :func:`_reclaim_one`. Kept as a separate function so the observe/reclaim
    boundary is an explicit, deterministically testable interleaving point
    (regression #3617).
    """
    now = _utc_now()
    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT t.task_id, t.lease_id
            FROM dispatcher_tasks t
            JOIN dispatcher_leases l ON t.lease_id = l.lease_id
            WHERE l.released_at IS NULL AND l.expires_at < ?
            ORDER BY l.expires_at
            """,
            (now,),
        ).fetchall()
    return [(row["task_id"], row["lease_id"]) for row in rows]


def _reclaim_one(
    store: SqliteStore,
    task_id: str,
    lease_id: str,
    actor: str,
) -> EventRecord | None:
    """Atomically reclaim a single observed expired lease, or no-op.

    Everything — the expiry/ownership recheck, the lease release, the task
    clear, and the release event — happens inside one ``BEGIN IMMEDIATE``
    transaction so a concurrent stale takeover cannot slip between the checks
    and the writes. The mutation is fenced on the *captured* ``lease_id``:

    - the task must still reference the captured expired lease, and
    - that lease must still be unreleased and still expired.

    If a takeover already released the observed lease and moved the task onto a
    replacement lease after :func:`_observe_expired_leases` sampled it, both
    conditional updates match zero rows and the function returns ``None`` rather
    than erasing the valid replacement claim (regression #3617).

    Returns the emitted ``task.released`` event on success, else ``None``.
    """
    now = _utc_now()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        task_row = conn.execute(
            "SELECT * FROM dispatcher_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        # Only reclaim while the task still references the captured expired
        # lease. A stale takeover repoints the task at a new lease, so this
        # guard is what keeps GC from clobbering the replacement.
        if task_row is None or task_row["lease_id"] != lease_id:
            conn.rollback()
            return None

        lease_row = conn.execute(
            "SELECT * FROM dispatcher_leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        if lease_row is None:
            conn.rollback()
            return None
        # Re-validate liveness under the write lock: a lease released or renewed
        # since observation must not be reclaimed.
        if lease_row["released_at"] is not None:
            conn.rollback()
            return None
        if _parse_rfc3339(lease_row["expires_at"]) >= _parse_rfc3339(now):
            conn.rollback()
            return None

        released = conn.execute(
            """
            UPDATE dispatcher_leases
            SET released_at = ?, release_reason = 'expired'
            WHERE lease_id = ? AND released_at IS NULL
            """,
            (now, lease_id),
        )
        if released.rowcount == 0:
            conn.rollback()
            return None

        next_status = "blocked" if task_row["blocked_reason"] is not None else "ready"
        cleared = conn.execute(
            """
            UPDATE dispatcher_tasks
            SET lease_id = NULL,
                claimed_by = NULL,
                last_heartbeat_at = NULL,
                lease_expires_at = NULL,
                status = ?,
                updated_at = ?
            WHERE task_id = ? AND lease_id = ?
            """,
            (next_status, now, task_id, lease_id),
        )
        if cleared.rowcount == 0:
            conn.rollback()
            return None

        event = EventRecord(
            event_id=_make_event_id(),
            timestamp=now,
            task_id=task_id,
            event_type="task.released",
            actor=actor,
            lease_id=lease_id,
            payload={"reason": "expired"},
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

    return event


def _reclaim_observed_leases(
    store: SqliteStore,
    observed: list[tuple[str, str]],
    actor: str,
) -> list[str]:
    """Reclaim each observed expired lease atomically; skip any that moved on.

    One lease's failure never aborts the sweep. Once ``_reclaim_one`` commits,
    the release is durable (including the ``task.released`` row written inside
    that transaction), so the task counts as reclaimed even if the best-effort
    JSONL mirror append then fails — a mirror error must not strand the
    remaining expired leases or drop the return list.
    """
    reclaimed: list[str] = []
    for task_id, lease_id in observed:
        try:
            event = _reclaim_one(store, task_id, lease_id, actor)
        except Exception:
            continue
        if event is None:
            continue
        reclaimed.append(task_id)
        if store._event_writer is not None:
            try:
                store._event_writer.append(event)
            except Exception:
                pass
    return reclaimed


def reclaim_expired_leases(
    store: SqliteStore,
    actor: str = "dispatcher-gc",
) -> list[str]:
    """Find and release all expired leases.

    Reclaims expired leases with audit trail attribution to the specified actor.
    Each reclamation rechecks the captured lease id, unreleased state, and expiry
    inside a single write transaction and clears task ownership only when the task
    still references the captured expired lease, so it can never erase a
    replacement lease acquired through ``claim(..., takeover_stale=True)`` after
    GC selected the old expired lease (#3617).

    Returns list of task_ids that had leases reclaimed.
    """
    observed = _observe_expired_leases(store)
    return _reclaim_observed_leases(store, observed, actor)
