from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.health_contract import DEFAULT_CONTRACT, WRITE_BLOCKED_STATES


class WritesBlockedError(RuntimeError):
    def __init__(self, state: str, reason: str | None, action: str) -> None:
        self.state = state
        self.reason = reason
        self.action = action
        reason_text = f": {reason}" if reason else ""
        super().__init__(f"Writes blocked for '{action}' while in '{state}' state{reason_text}")


class WriteGuard:
    def __init__(self, snapshot_fn: Callable[[], dict[str, Any]] | None = None) -> None:
        self.snapshot_fn = snapshot_fn or DEFAULT_CONTRACT.evaluate

    def assert_writes_allowed(self, action: str) -> None:
        snapshot = self.snapshot_fn()
        state = snapshot.get("state") or ""
        if state in WRITE_BLOCKED_STATES:
            reason = snapshot.get("reason")
            raise WritesBlockedError(state, reason, action)


DEFAULT_WRITE_GUARD = WriteGuard()

__all__ = ["WriteGuard", "DEFAULT_WRITE_GUARD", "WritesBlockedError"]
