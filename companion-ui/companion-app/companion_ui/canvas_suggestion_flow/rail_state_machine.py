"""Canvas rail state machine for the Canvas bounded suggestion flow (#870).

Implements the 9-state machine defined in CANVAS_SUGGESTION_FLOW.md.
Internal state names use the canonical snake_case contract names.
DOM alias names are rendering-only; they must not become internal contract names.

This is NOT Canvas Core session state. Canvas Core applies body edits directly
in-place. The suggestion flow requires user approval at each proposal before any
write occurs.
"""

from __future__ import annotations

# Canonical internal state names (snake_case). Source: CANVAS_SUGGESTION_FLOW.md.
RAIL_STATES: frozenset[str] = frozenset({
    "idle",
    "thinking",
    "staged_body",
    "staged_governance",
    "apply_pending",
    "governance_pending",
    "applied",
    "discarded",
    "blocked",
})

# DOM alias names for CSS/HTML rendering. Internal code must use canonical names.
DOM_ALIAS: dict[str, str] = {
    "idle":               "idle",
    "thinking":           "thinking",
    "staged_body":        "staged-body",
    "staged_governance":  "staged-gov",
    "apply_pending":      "pending-apply",
    "governance_pending": "pending-gov",
    "applied":            "applied",
    "discarded":          "discarded",
    "blocked":            "blocked",
}

# States that prevent further user action until auto-transition or acknowledgement.
TERMINAL_PRESENTATION_STATES: frozenset[str] = frozenset({"applied", "discarded", "blocked"})

# States in which the user has a staged proposal to act on.
STAGED_STATES: frozenset[str] = frozenset({"staged_body", "staged_governance"})

# Legal transitions: canonical from_state → set of reachable to_states.
# Forbidden invariants encoded here:
#   - No skip from staged_* directly to applied/idle without the pending state.
#   - Governance proposals never enter apply_pending.
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "idle":               frozenset({"thinking"}),
    "thinking":           frozenset({"staged_body", "staged_governance", "blocked", "idle"}),
    "staged_body":        frozenset({"apply_pending", "discarded"}),
    "staged_governance":  frozenset({"governance_pending", "discarded"}),
    "apply_pending":      frozenset({"applied", "staged_body"}),      # staged_body on error
    "governance_pending": frozenset({"idle", "staged_governance"}),   # staged_governance on error
    "applied":            frozenset({"idle"}),
    "discarded":          frozenset({"idle"}),
    "blocked":            frozenset({"idle"}),
}


class CanvasRailStateMachine:
    """State machine for the Canvas bounded suggestion flow rail.

    Tracks the single active state of the suggestion rail and enforces the
    allowed-transition table from CANVAS_SUGGESTION_FLOW.md.

    Does not call canvas_writer, GovernanceRouter, or session_log.
    Caller is responsible for performing the associated side-effect and then
    calling transition() with the result state.
    """

    def __init__(self, initial_state: str = "idle") -> None:
        if initial_state not in RAIL_STATES:
            raise ValueError(f"Unknown initial rail state: {initial_state!r}")
        self._state = initial_state
        self._error: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def dom_alias(self) -> str:
        return DOM_ALIAS[self._state]

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def is_terminal_presentation(self) -> bool:
        return self._state in TERMINAL_PRESENTATION_STATES

    @property
    def is_staged(self) -> bool:
        return self._state in STAGED_STATES

    @property
    def composer_enabled(self) -> bool:
        return self._state == "idle"

    def transition(self, to_state: str, *, error: str | None = None) -> None:
        """Transition to to_state, raising ValueError on illegal moves.

        error is only meaningful on error-path transitions back to staged_* states.
        """
        if to_state not in RAIL_STATES:
            raise ValueError(f"Unknown rail state: {to_state!r}")
        if to_state not in _LEGAL_TRANSITIONS[self._state]:
            raise ValueError(
                f"Illegal canvas rail transition: {self._state!r} → {to_state!r}"
            )
        self._state = to_state
        self._error = error

    def allowed_transitions(self) -> frozenset[str]:
        """Return the set of states reachable from the current state."""
        return _LEGAL_TRANSITIONS[self._state]


def make_stub_rail(initial_state: str = "idle") -> CanvasRailStateMachine:
    """Return a CanvasRailStateMachine in the given initial state for testing."""
    return CanvasRailStateMachine(initial_state=initial_state)
