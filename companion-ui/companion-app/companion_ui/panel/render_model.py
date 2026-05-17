"""Panel render model / component shell contract (#1039).

Panel is the artifact-local intent manifestation and confirmation surface.
It is NOT Canvas Core, NOT Canvas bounded suggestion flow, and never writes
vault files directly.

Source contracts:
- companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
- companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
- docs/PANEL_AGENT.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


PANEL_STATES_REQUIRED: set[str] = {
    "idle",
    "running",
    "proposals-staged",
    "confirming",
    "executing",
    "receipt-displayed",
    "no-match",
    "blocked",
}

# Named for forward-compatibility; implementations must not preclude them.
PANEL_STATES_FUTURE: set[str] = {
    "clarification-needed",
    "plan-staged",
    "capability-needed",
    "partial-complete",
}

PANEL_STATES_ALL: set[str] = PANEL_STATES_REQUIRED | PANEL_STATES_FUTURE

# Legal state transitions for the Panel surface state machine.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "idle":              {"running", "no-match", "blocked"},
    "running":           {"proposals-staged", "no-match", "blocked", "clarification-needed"},
    "proposals-staged":  {"confirming", "idle", "blocked", "partial-complete"},
    "confirming":        {"executing", "blocked", "proposals-staged"},
    "executing":         {"receipt-displayed", "blocked", "partial-complete"},
    "receipt-displayed": {"idle"},
    "no-match":          {"idle", "running"},
    "blocked":           {"idle"},
    "clarification-needed": {"running", "idle"},
    "plan-staged":       {"confirming", "idle"},
    "capability-needed": {"idle"},
    "partial-complete":  {"confirming", "receipt-displayed", "idle"},
}


@dataclass
class PanelRenderState:
    """Render state snapshot for the Panel surface bound to a single artifact.

    artifact_id is required — Panel is always artifact-local, never global.
    message is set for states that carry a user-facing explanation
    (no-match reason, blocked reason).
    """

    artifact_id: str
    state: str = "idle"
    message: Optional[str] = None
    proposal_count: int = 0

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("artifact_id is required — Panel is artifact-local")
        if self.state not in PANEL_STATES_ALL:
            raise ValueError(f"Unknown Panel state: {self.state!r}")

    def transition(self, to_state: str) -> None:
        """Apply a Panel state transition, raising ValueError on illegal moves."""
        if to_state not in PANEL_STATES_ALL:
            raise ValueError(f"Unknown Panel target state: {to_state!r}")
        allowed = _LEGAL_TRANSITIONS.get(self.state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Illegal Panel state transition: {self.state!r} → {to_state!r}"
            )
        self.state = to_state
        if to_state not in ("no-match", "blocked"):
            self.message = None

    @property
    def has_proposals(self) -> bool:
        return self.state == "proposals-staged" and self.proposal_count > 0

    @property
    def is_visible_failure(self) -> bool:
        """True for states that must be rendered visibly to the user."""
        return self.state in ("no-match", "blocked")

    @property
    def awaiting_user_decision(self) -> bool:
        return self.state in ("proposals-staged", "clarification-needed", "plan-staged")


def render_panel_state(render_state: PanelRenderState) -> dict:
    """Return a serialisable render adapter dict for the given Panel state.

    This is a pure-function adapter: it does not write vault files, call
    runtime APIs, or perform execution.  It maps model state to a
    representation suitable for driving a UI layer.
    """
    base: dict = {
        "artifact_id": render_state.artifact_id,
        "state": render_state.state,
        "visible": True,
        "message": render_state.message,
    }

    if render_state.state == "idle":
        base["label"] = "Panel ready"
    elif render_state.state == "running":
        base["label"] = "Thinking…"
        base["loading"] = True
    elif render_state.state == "proposals-staged":
        base["label"] = f"{render_state.proposal_count} proposal(s) ready"
        base["proposal_count"] = render_state.proposal_count
    elif render_state.state == "confirming":
        base["label"] = "Confirming…"
        base["loading"] = True
    elif render_state.state == "executing":
        base["label"] = "Executing…"
        base["loading"] = True
    elif render_state.state == "receipt-displayed":
        base["label"] = "Done — see receipt"
    elif render_state.state == "no-match":
        base["label"] = "No proposals for this note"
        base["message"] = render_state.message or "Panel ran but found no actionable proposals."
    elif render_state.state == "blocked":
        base["label"] = "Blocked"
        base["message"] = render_state.message or "Execution was blocked."
    elif render_state.state == "clarification-needed":
        base["label"] = "Clarification needed"
    elif render_state.state == "plan-staged":
        base["label"] = "Plan ready for review"
    elif render_state.state == "capability-needed":
        base["label"] = "Capability not available"
    elif render_state.state == "partial-complete":
        base["label"] = "Some proposals executed"

    return base
