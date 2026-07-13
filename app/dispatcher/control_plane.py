"""Logical control-plane state and recovery observations for dispatcher."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dispatcher.config import DEFAULT_DB_NAME, DEFAULT_EVENTS_NAME, DispatcherPaths
from app.dispatcher.schema import SCHEMA_VERSION
from app.dispatcher.store import SqliteStore

STATE_KEY = "control_plane_state"
MODES = frozenset({"normal", "degraded", "recovery"})
_ALLOWED = {"normal": {"degraded"}, "degraded": {"recovery"}, "recovery": {"normal"}}
_REQUIRED_TABLES = frozenset(
    {"dispatcher_tasks", "dispatcher_leases", "dispatcher_events", "dispatcher_meta"}
)
_REQUIRED_COLUMNS = {
    "dispatcher_tasks": frozenset(
        {
            "task_id",
            "issue_number",
            "title",
            "status",
            "priority",
            "repo",
            "source_anchor_refs",
            "claimed_by",
            "lease_id",
            "lease_expires_at",
            "linked_pr",
            "blocked_reason",
            "last_heartbeat_at",
            "sync_state",
            "created_at",
            "updated_at",
        }
    ),
    "dispatcher_leases": frozenset(
        {
            "lease_id",
            "resource",
            "holder",
            "ttl_seconds",
            "acquired_at",
            "expires_at",
            "heartbeat_at",
            "released_at",
            "release_reason",
        }
    ),
    "dispatcher_events": frozenset(
        {
            "event_id",
            "timestamp",
            "task_id",
            "event_type",
            "actor",
            "lease_id",
            "payload",
        }
    ),
    "dispatcher_meta": frozenset({"key", "value"}),
}
# Every dispatcher write path uses an identifier as an ``ON CONFLICT`` target
# (or relies on it being unique).  Column presence alone is therefore not a
# usable-schema check: a hand-created table can have the right columns but no
# primary key or UNIQUE index, and will only fail later when a writer runs.
_REQUIRED_UNIQUE_KEYS = {
    "dispatcher_tasks": ("task_id",),
    "dispatcher_leases": ("lease_id",),
    "dispatcher_events": ("event_id",),
    "dispatcher_meta": ("key",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dispatcher_schema_error(conn: sqlite3.Connection) -> str | None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        return f"missing dispatcher tables: {', '.join(missing)}"
    for table, required in _REQUIRED_COLUMNS.items():
        columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = sorted(required - columns)
        if missing_columns:
            return f"missing dispatcher columns in {table}: {', '.join(missing_columns)}"
    for table, required_key in _REQUIRED_UNIQUE_KEYS.items():
        if not _has_unique_key(conn, table, required_key):
            return (
                f"missing required unique key in {table}: "
                f"{', '.join(required_key)}"
            )
    row = conn.execute(
        "SELECT value FROM dispatcher_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return "missing dispatcher schema_version"
    try:
        version = int(row[0])
    except (TypeError, ValueError):
        return "invalid dispatcher schema_version"
    if version not in {1, SCHEMA_VERSION}:
        return f"unsupported dispatcher schema_version: {version}"
    return None


def _has_unique_key(
    conn: sqlite3.Connection, table: str, required_key: tuple[str, ...]
) -> bool:
    """Return whether ``table`` enforces uniqueness for ``required_key``.

    SQLite represents table primary keys and explicit ``UNIQUE`` constraints
    through slightly different pragma surfaces.  Inspect both so recovery
    commands accept compatible legacy databases without certifying a shape
    that a normal dispatcher write cannot use.
    """
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    primary_key = tuple(
        str(row[1])
        for row in sorted(columns, key=lambda row: int(row[5]))
        if int(row[5]) > 0
    )
    if primary_key == required_key:
        return True

    for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not bool(index[2]):
            continue
        index_columns = tuple(
            str(row[2])
            for row in conn.execute(f"PRAGMA index_info({index[1]})").fetchall()
        )
        if index_columns == required_key:
            return True
    return False


def state(store: SqliteStore) -> dict[str, Any]:
    raw = store.get_meta(STATE_KEY)
    return _parse_state(raw)


def readonly_state(db_path: Path) -> dict[str, Any]:
    """Read control-plane state without initializing or migrating its database.

    ``status`` is an observation command.  It must be safe to run against a
    missing, incomplete, or legacy dispatcher database, rather than opening it
    through :class:`SqliteStore`, whose normal connection path self-heals the
    schema.  SQLite's ``mode=ro`` URI guarantees this connection cannot create
    the database or modify its schema; validating the full dispatcher shape
    first also prevents status from treating a partial database as usable.
    """
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        schema_error = _dispatcher_schema_error(conn)
        if schema_error is not None:
            raise ValueError(schema_error)
        row = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key = ?", (STATE_KEY,)
        ).fetchone()
    return _parse_state(None if row is None else str(row[0]))


def _parse_state(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"mode": "normal", "revision": 0, "updated_at": None, "activation_id": None}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Dispatcher control-plane state is malformed") from exc
    if not isinstance(value, dict) or value.get("mode") not in MODES or not isinstance(value.get("revision"), int):
        raise ValueError("Dispatcher control-plane state is malformed")
    return value


def health(paths: DispatcherPaths) -> dict[str, Any]:
    result: dict[str, Any] = {
        "db": {"path": str(paths.db_path), "exists": paths.db_path.exists()},
        "events": {"path": str(paths.events_path), "exists": paths.events_path.exists()},
        "ok": False,
    }
    if not paths.db_path.exists():
        result["db"]["error"] = "missing"
        return result
    if not paths.events_path.exists():
        result["events"]["error"] = "missing"
        return result
    try:
        with sqlite3.connect(paths.db_path, timeout=0) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            schema_error = _dispatcher_schema_error(conn)
            if schema_error is not None:
                result["db"]["error"] = schema_error
                return result
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        result["db"].update({"integrity": integrity, "writable": True})
    except sqlite3.Error as exc:
        result["db"]["error"] = str(exc)
        return result
    try:
        lines = 0
        if paths.events_path.exists():
            for lines, line in enumerate(paths.events_path.read_text(encoding="utf-8").splitlines(), 1):
                json.loads(line)
        result["events"]["valid_lines"] = lines
    except (OSError, json.JSONDecodeError) as exc:
        result["events"]["error"] = str(exc)
        return result
    result["ok"] = result["db"]["integrity"] == "ok"
    return result


def transition(store: SqliteStore, paths: DispatcherPaths, mode: str, *, activation_id: str, expected_revision: int) -> dict[str, Any]:
    if mode not in MODES or not activation_id:
        raise ValueError("Control-plane mode and activation id are required")
    proof = health(paths)
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM dispatcher_meta WHERE key = ?", (STATE_KEY,)).fetchone()
        current = {"mode": "normal", "revision": 0} if row is None else json.loads(row["value"])
        if current.get("revision") != expected_revision:
            conn.rollback()
            raise ValueError("Control-plane state changed concurrently; re-read status before retrying")
        if mode not in _ALLOWED.get(current.get("mode"), set()):
            conn.rollback()
            raise ValueError(f"Invalid control-plane transition: {current.get('mode')} -> {mode}")
        if mode == "degraded" and proof["ok"]:
            conn.rollback()
            raise ValueError("Refusing degraded mode while dispatcher health is ok")
        if mode == "normal" and not proof["ok"]:
            conn.rollback()
            raise ValueError("Refusing normal mode until dispatcher health is verified")
        next_state = {"mode": mode, "revision": expected_revision + 1, "updated_at": _now(), "activation_id": activation_id, "health": proof}
        conn.execute("INSERT INTO dispatcher_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (STATE_KEY, json.dumps(next_state, sort_keys=True)))
        conn.commit()
    return next_state


def backup(paths: DispatcherPaths, destination: Path) -> dict[str, str]:
    resolved_destination = destination.resolve()
    source_paths = {paths.db_path.resolve(), paths.events_path.resolve()}
    target = destination / DEFAULT_DB_NAME
    events_target = destination / DEFAULT_EVENTS_NAME
    target_paths = {target.resolve(), events_target.resolve()}
    if (
        resolved_destination == paths.state_dir.resolve()
        or resolved_destination.is_relative_to(paths.state_dir.resolve())
        or any(source.is_relative_to(resolved_destination) for source in source_paths)
        or bool(source_paths & target_paths)
    ):
        raise ValueError("Backup destination must be separate from dispatcher state")
    if destination.exists():
        raise ValueError("Backup destination must not already exist")
    proof = health(paths)
    if not proof["ok"]:
        raise ValueError("Dispatcher state is unsafe to back up")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        staged_db = staging / DEFAULT_DB_NAME
        staged_events = staging / DEFAULT_EVENTS_NAME
        with sqlite3.connect(paths.db_path) as source, sqlite3.connect(staged_db) as output:
            source.backup(output)
        shutil.copy2(paths.events_path, staged_events)
        staging.replace(destination)
    except (OSError, sqlite3.Error) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(f"Dispatcher backup failed: {exc}") from exc
    return {"db": str(target), "events": str(events_target), "created_at": _now()}


def restore(backup_dir: Path, target: DispatcherPaths) -> dict[str, str]:
    if backup_dir.resolve() == target.state_dir.resolve() or (
        target.state_dir.exists() and any(target.state_dir.iterdir())
    ):
        raise ValueError("Restore target must be a separate, empty state root")
    target_root = target.state_dir.resolve()
    try:
        db_relative = target.db_path.resolve().relative_to(target_root)
        events_relative = target.events_path.resolve().relative_to(target_root)
    except ValueError as exc:
        raise ValueError("Restore artifacts must be inside the target state root") from exc
    if db_relative == events_relative:
        raise ValueError("Restore database and events targets must be distinct")
    source = backup_dir / DEFAULT_DB_NAME
    if not source.exists():
        raise ValueError(f"Backup database missing: {source}")
    events = backup_dir / DEFAULT_EVENTS_NAME
    if not events.exists():
        raise ValueError(f"Backup events missing: {events}")
    try:
        for line in events.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Backup events are invalid: {exc}") from exc
    try:
        with sqlite3.connect(source, timeout=0) as input_db:
            source_integrity = input_db.execute("PRAGMA integrity_check").fetchone()[0]
            schema_error = _dispatcher_schema_error(input_db)
    except sqlite3.Error as exc:
        raise ValueError(f"Backup database is invalid: {exc}") from exc
    if source_integrity != "ok":
        raise ValueError(f"Backup database integrity failed: {source_integrity}")
    if schema_error is not None:
        raise ValueError(f"Backup database is invalid: {schema_error}")
    target.state_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.state_dir.name}.tmp-", dir=target.state_dir.parent)
    )
    staged_db = staging / db_relative
    staged_events = staging / events_relative
    try:
        staged_db.parent.mkdir(parents=True, exist_ok=True)
        staged_events.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as input_db, sqlite3.connect(staged_db) as output:
            input_db.backup(output)
        with sqlite3.connect(staged_db) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Restored database integrity failed: {integrity}")
        shutil.copy2(events, staged_events)
        staging.replace(target.state_dir)
    except (OSError, sqlite3.Error) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(f"Dispatcher restore failed: {exc}") from exc
    except ValueError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"db": str(target.db_path), "events": str(target.events_path), "integrity": integrity}
