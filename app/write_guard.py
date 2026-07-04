from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.health_contract import DEFAULT_CONTRACT, WRITE_BLOCKED_STATES

# Named bootstrap escape (#2877): actions that provision a brand-new vault
# *before* a vault has been selected (T-scaffold in formal-model.md §2.3).
# These must survive ordinary runtime health degradation
# (``safe_mode``/``unhealthy``), otherwise a degraded runtime would deadlock
# the very provisioning that could heal it. The escape is explicit and named
# here — the action string is the auditable escape token, not silent absence
# of a guard. A guard constructed without an action in its allow-list still
# denies that action under a blocked state, so every seam that consults the
# guard remains genuinely gated.
DEFAULT_BOOTSTRAP_ACTIONS: frozenset[str] = frozenset({"yggdrasil.scaffold"})


class WritesBlockedError(RuntimeError):
    def __init__(self, state: str, reason: str | None, action: str) -> None:
        self.state = state
        self.reason = reason
        self.action = action
        reason_text = f": {reason}" if reason else ""
        super().__init__(f"Writes blocked for '{action}' while in '{state}' state{reason_text}")


class WriteGuard:
    def __init__(
        self,
        snapshot_fn: Callable[[], dict[str, Any]] | None = None,
        *,
        bootstrap_actions: Iterable[str] = DEFAULT_BOOTSTRAP_ACTIONS,
    ) -> None:
        self.snapshot_fn = snapshot_fn or DEFAULT_CONTRACT.evaluate
        # Named allow-list of bootstrap actions permitted under health-blocked
        # states. Frozen so a guard's escape policy cannot be mutated in place.
        self.bootstrap_actions: frozenset[str] = frozenset(bootstrap_actions)

    def assert_writes_allowed(self, action: str) -> None:
        snapshot = self.snapshot_fn()
        state = snapshot.get("state") or ""
        if state in WRITE_BLOCKED_STATES and action not in self.bootstrap_actions:
            reason = snapshot.get("reason")
            raise WritesBlockedError(state, reason, action)


DEFAULT_WRITE_GUARD = WriteGuard()

__all__ = [
    "WriteGuard",
    "DEFAULT_WRITE_GUARD",
    "DEFAULT_BOOTSTRAP_ACTIONS",
    "WritesBlockedError",
]
