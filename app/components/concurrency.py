from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Dict, Protocol, Tuple


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)


class DedupTaskQueue:
    def __init__(self, clock: Clock | None = None, ttl_seconds: float = 300.0) -> None:
        self._clock = clock or SystemClock()
        self._ttl = float(ttl_seconds)
        self._entries: Dict[str, float] = {}

    def try_acquire(self, key: str) -> bool:
        if not key:
            return False
        now = self._clock.now()
        self._purge(now)
        expires_at = self._entries.get(key)
        if expires_at is not None and expires_at > now:
            return False
        self._entries[key] = now + self._ttl
        return True

    def release(self, key: str) -> None:
        self._entries.pop(key, None)

    def stats(self) -> dict[str, float | int]:
        return {"size": len(self._entries), "ttl_seconds": self._ttl}

    def _purge(self, now: float) -> None:
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

class EventDedupStore:
    def __init__(self, clock: Clock | None = None, ttl_seconds: float = 3600.0) -> None:
        self._clock = clock or SystemClock()
        self._ttl = float(ttl_seconds)
        self._entries: Dict[str, float] = {}

    def seen(self, event_id: str | None) -> bool:
        if not event_id:
            return False
        now = self._clock.now()
        self._purge(now)
        expires_at = self._entries.get(event_id)
        if expires_at is not None and expires_at > now:
            return True
        self._entries[event_id] = now + self._ttl
        return False

    def _purge(self, now: float) -> None:
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()


class IdempotencyGuard:
    def __init__(self, clock: Clock | None = None, ttl_seconds: float | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ttl = float(ttl_seconds) if ttl_seconds is not None else None
        self._entries: Dict[Tuple[str, str], float] = {}

    def seen_action(self, note_id: str, action_id: str) -> bool:
        if not note_id or not action_id:
            return False
        now = self._clock.now()
        self._purge(now)
        expires_at = self._entries.get((note_id, action_id))
        if expires_at is None:
            return False
        return expires_at > now

    def mark_action(self, note_id: str, action_id: str) -> None:
        if not note_id or not action_id:
            return
        now = self._clock.now()
        expires_at = now + self._ttl if self._ttl is not None else float("inf")
        self._entries[(note_id, action_id)] = expires_at

    def _purge(self, now: float) -> None:
        if self._ttl is None:
            return
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


class VersionMismatch(RuntimeError):
    pass


class OptimisticWriteGuard:
    def compute_version(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def read_version(self, path: Path) -> str:
        return self.compute_version(path.read_bytes())

    def write_if_unchanged(self, path: Path, expected_version: str, new_content: bytes | str) -> None:
        current_version = self.read_version(path)
        if current_version != expected_version:
            raise VersionMismatch(f"version mismatch for {path}")
        data = new_content.encode("utf-8") if isinstance(new_content, str) else new_content
        path.write_bytes(data)


__all__ = [
    "Clock",
    "SystemClock",
    "FakeClock",
    "DedupTaskQueue",
    "EventDedupStore",
    "IdempotencyGuard",
    "OptimisticWriteGuard",
    "VersionMismatch",
]
