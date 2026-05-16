"""Canvas Core session lifecycle state contract.

Canvas Core is direct in-place co-authoring of the active note body during a
user-present session.  This module defines the session lifecycle state machine
and the authority rules that govern when body edits are permitted.

This is NOT Canvas bounded suggestion flow state (#868–#874).  Canvas bounded
suggestion flow is a separate, staged-suggestion pattern with pre-commit
approval gates.  Canvas Core applies body edits in place by default; undo is
the rollback mechanism.
"""

CANVAS_SESSION_STATES = {"start", "active", "paused", "interrupted", "closed"}

# Legal transitions: from_state -> set of reachable to_states
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "start":       {"active"},
    "active":      {"paused", "interrupted", "closed"},
    "paused":      {"active", "closed"},
    "interrupted": {"active", "closed"},
    "closed":      set(),
}

# States that authorise direct assistant body edits (user-present authority).
_BODY_EDIT_STATES = {"active"}

# States that retain session recovery potential (session is not durable-closed).
_RECOVERABLE_STATES = {"paused", "interrupted"}


class CanvasSessionState:
    """Canvas session lifecycle state for a single-note co-authoring session."""

    def __init__(self, *, artifact_id: str, initial_state: str = "start") -> None:
        if initial_state not in CANVAS_SESSION_STATES:
            raise ValueError(f"Unknown initial state: {initial_state!r}")
        self.artifact_id = artifact_id
        self._state = initial_state

    @property
    def state(self) -> str:
        return self._state

    def transition(self, to_state: str) -> None:
        """Apply a state transition, raising ValueError on illegal moves."""
        if to_state not in CANVAS_SESSION_STATES:
            raise ValueError(f"Unknown target state: {to_state!r}")
        if to_state not in _LEGAL_TRANSITIONS[self._state]:
            raise ValueError(
                f"Illegal Canvas session transition: {self._state!r} → {to_state!r}"
            )
        self._state = to_state

    @property
    def body_edits_allowed(self) -> bool:
        """True only when session is active and user-present authority is granted."""
        return self._state in _BODY_EDIT_STATES

    @property
    def recovery_needed(self) -> bool:
        """True when session is paused or interrupted and can be re-entered."""
        return self._state in _RECOVERABLE_STATES

    @property
    def is_closed(self) -> bool:
        return self._state == "closed"

    def assert_body_edit_allowed(self) -> None:
        """Raise PermissionError when body edits are not authorised."""
        if not self.body_edits_allowed:
            raise PermissionError(
                f"Direct body edits are not allowed in Canvas session state {self._state!r}. "
                "Session must be active and user-present."
            )
