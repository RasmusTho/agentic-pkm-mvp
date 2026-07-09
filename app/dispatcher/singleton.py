"""Local dispatcher singleton coordination state."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.dispatcher.config import DispatcherPaths

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback for local tooling.
    fcntl = None  # type: ignore[assignment]

SINGLETON_RECORD_NAME = "dispatcher.singleton.json"
SINGLETON_GUARD_NAME = ".dispatcher.singleton.guard"
DEFAULT_SINGLETON_TTL_SECONDS = 5400

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.Lock] = {}


class DispatcherSingletonBusyError(RuntimeError):
    """Raised when another process is starting dispatcher state."""


@dataclass(frozen=True)
class SingletonPaths:
    record_path: Path
    guard_path: Path


def singleton_paths(paths: DispatcherPaths) -> SingletonPaths:
    return SingletonPaths(
        record_path=paths.state_dir / SINGLETON_RECORD_NAME,
        guard_path=paths.state_dir / SINGLETON_GUARD_NAME,
    )


def start_singleton(
    paths: DispatcherPaths,
    *,
    holder: str,
    ttl_seconds: int = DEFAULT_SINGLETON_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create or refresh dispatcher singleton coordination state.

    This does not run work or acquire task leases. It records that one local
    dispatcher state root is the active coordination root for a bounded TTL.
    """

    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    holder = _normalize_holder(holder)
    current = _utc_now(now)
    paths.ensure()
    singleton = singleton_paths(paths)

    with _locked_guard(singleton.guard_path):
        existing = _read_record(singleton.record_path)
        existing_status = singleton_status(paths, now=current)
        if existing and existing_status["singleton"]["state"] == "active":
            return {
                "started": False,
                "recovered_stale": False,
                **existing_status,
            }

        expires_at = current + timedelta(seconds=ttl_seconds)
        record = {
            "version": 1,
            "holder": holder,
            "pid": os.getpid(),
            "state_dir": str(paths.state_dir),
            "db_path": str(paths.db_path),
            "events_path": str(paths.events_path),
            "acquired_at": _format_utc(current),
            "heartbeat_at": _format_utc(current),
            "expires_at": _format_utc(expires_at),
            "ttl_seconds": ttl_seconds,
        }
        _write_record(singleton.record_path, record)
        status = singleton_status(paths, now=current)
        return {
            "started": True,
            "recovered_stale": bool(existing),
            **status,
        }


def singleton_status(
    paths: DispatcherPaths,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc_now(now)
    singleton = singleton_paths(paths)
    record = _read_record(singleton.record_path)
    state = "missing"
    active = False
    stale = False
    if record is not None:
        expires_at = _parse_utc(record.get("expires_at"))
        if expires_at is not None and expires_at > current:
            state = "active"
            active = True
        else:
            state = "stale"
            stale = True

    return {
        "state_dir": str(paths.state_dir),
        "db_path": str(paths.db_path),
        "db_exists": paths.db_path.exists(),
        "events_path": str(paths.events_path),
        "events_exists": paths.events_path.exists(),
        "singleton": {
            "path": str(singleton.record_path),
            "guard_path": str(singleton.guard_path),
            "exists": record is not None,
            "state": state,
            "active": active,
            "stale": stale,
            "holder": record.get("holder") if record else None,
            "pid": record.get("pid") if record else None,
            "acquired_at": record.get("acquired_at") if record else None,
            "heartbeat_at": record.get("heartbeat_at") if record else None,
            "expires_at": record.get("expires_at") if record else None,
            "ttl_seconds": record.get("ttl_seconds") if record else None,
        },
    }


def _normalize_holder(holder: str) -> str:
    if not isinstance(holder, str) or not holder.strip():
        raise ValueError("holder must be a non-empty string")
    return holder.strip()


def _read_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


@contextmanager
def _locked_guard(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _thread_lock_for(path)
    with thread_lock:
        with path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DispatcherSingletonBusyError(
                        "dispatcher singleton start is already in progress"
                    ) from exc
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    lock_key = lock_path.resolve(strict=False)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[lock_key] = lock
        return lock


def _utc_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc, microsecond=0)
    return now.astimezone(timezone.utc).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except ValueError:
        return None
