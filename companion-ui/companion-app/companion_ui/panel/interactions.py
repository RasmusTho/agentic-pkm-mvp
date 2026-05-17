"""Panel confirm/correct/reject interaction state model (#1041).

Implements per-proposal interaction state transitions.  This is UI interaction
state only — it does not execute runtime actions, write vault files, or call
runtime APIs.  The runtime owns execution authority, receipts, and durable
projection.

Invariants enforced here:
- Confirmation is explicit and per-proposal. No bulk confirmation.
- Confirming moves to confirming/submitted state; it does not execute locally.
- Same-turn generated→executed transition is not a legal state path.
- Correction produces a corrected-proposal state without silently mutating the
  original.
- Rejection marks the proposal declined with no execution.

Source contract: companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md :: Part 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Interaction states for a single proposal.
PROPOSAL_INTERACTION_STATES: set[str] = {
    "staged",
    "confirming",
    "submitted",
    "corrected",
    "correction-pending",
    "rejected",
    "blocked",
    "clarification-needed",
}

# Legal per-proposal interaction transitions.
# "staged" is the only entry point that accepts user actions.
# "submitted" is terminal for the Companion UI — runtime takes over.
_LEGAL_INTERACTION_TRANSITIONS: dict[str, set[str]] = {
    "staged":              {"confirming", "corrected", "rejected", "clarification-needed"},
    "confirming":          {"submitted", "blocked", "staged"},
    "submitted":           set(),           # terminal in UI; runtime drives from here
    "corrected":           {"confirming", "rejected", "correction-pending"},
    "correction-pending":  {"corrected", "rejected", "staged"},
    "rejected":            set(),           # terminal — user declined
    "blocked":             {"staged"},      # user may retry after inspecting block
    "clarification-needed": {"staged", "corrected"},
}

# States from which "confirm" action is allowed.
_CONFIRMABLE_STATES: set[str] = {"staged", "corrected"}

# States from which "correct" action is allowed.
_CORRECTABLE_STATES: set[str] = {"staged"}

# States from which "reject" action is allowed.
_REJECTABLE_STATES: set[str] = {"staged", "corrected", "correction-pending"}


@dataclass
class ProposalInteractionState:
    """Per-proposal interaction state machine for the Panel surface.

    This model tracks the UI-side interaction state for a single proposal.
    It does not execute anything — confirm() records that the user has
    authorised submission; the actual runtime call is the responsibility of
    a higher-level orchestrator that reads this state and contacts the endpoint.
    """

    proposal_id: str
    state: str = "staged"
    correction_text: Optional[str] = None
    clarification_question: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.proposal_id:
            raise ValueError("proposal_id is required")
        if self.state not in PROPOSAL_INTERACTION_STATES:
            raise ValueError(f"Unknown interaction state: {self.state!r}")

    def _transition(self, to_state: str) -> None:
        if to_state not in PROPOSAL_INTERACTION_STATES:
            raise ValueError(f"Unknown interaction target state: {to_state!r}")
        allowed = _LEGAL_INTERACTION_TRANSITIONS.get(self.state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Illegal Panel interaction transition: {self.state!r} → {to_state!r}"
            )
        self.state = to_state

    def confirm(self) -> None:
        """Record that the user has explicitly confirmed this proposal.

        Moves to 'confirming' state.  Does NOT execute the proposal locally.
        Same-turn execution (staged → executed) is not a valid path.
        """
        if self.state not in _CONFIRMABLE_STATES:
            raise ValueError(
                f"Cannot confirm proposal in state {self.state!r}. "
                f"Confirmable states: {_CONFIRMABLE_STATES!r}"
            )
        self._transition("confirming")

    def mark_submitted(self) -> None:
        """Record that the confirmation has been submitted to the runtime.

        'submitted' is terminal for the UI layer.  Runtime drives from here.
        """
        self._transition("submitted")

    def correct(self, correction_text: str) -> None:
        """Record that the user has corrected the proposal before confirming.

        Creates a new corrected state without silently mutating the staged state.
        """
        if self.state not in _CORRECTABLE_STATES:
            raise ValueError(
                f"Cannot correct proposal in state {self.state!r}. "
                f"Correctable states: {_CORRECTABLE_STATES!r}"
            )
        if not correction_text or not correction_text.strip():
            raise ValueError("correction_text must be non-empty")
        self.correction_text = correction_text
        self._transition("corrected")

    def reject(self) -> None:
        """Record that the user has declined this proposal.

        'rejected' is terminal — no execution follows.
        """
        if self.state not in _REJECTABLE_STATES:
            raise ValueError(
                f"Cannot reject proposal in state {self.state!r}. "
                f"Rejectable states: {_REJECTABLE_STATES!r}"
            )
        self._transition("rejected")

    def mark_blocked(self) -> None:
        """Record that the runtime returned a blocked response."""
        self._transition("blocked")

    def request_clarification(self, question: Optional[str] = None) -> None:
        """Record that clarification is needed before this proposal can proceed."""
        self.clarification_question = question
        self._transition("clarification-needed")

    @property
    def is_terminal(self) -> bool:
        return self.state in ("submitted", "rejected")

    @property
    def awaiting_runtime(self) -> bool:
        return self.state in ("confirming", "submitted")

    @property
    def user_action_required(self) -> bool:
        return self.state in ("staged", "corrected", "correction-pending",
                               "blocked", "clarification-needed")

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "state": self.state,
            "correction_text": self.correction_text,
            "clarification_question": self.clarification_question,
            "is_terminal": self.is_terminal,
            "awaiting_runtime": self.awaiting_runtime,
            "user_action_required": self.user_action_required,
        }


class PanelInteractionSession:
    """Tracks per-proposal interaction states for a Panel surface session.

    Enforces no-bulk-confirm: each proposal must be interacted with individually.
    Same-turn execution is not supported — generated proposals must go through
    the explicit confirm → submit → runtime flow.
    """

    def __init__(self, artifact_id: str) -> None:
        if not artifact_id:
            raise ValueError("artifact_id is required")
        self.artifact_id = artifact_id
        self._proposals: dict[str, ProposalInteractionState] = {}

    def register_proposal(self, proposal_id: str) -> ProposalInteractionState:
        """Register a newly staged proposal for individual interaction tracking."""
        if proposal_id in self._proposals:
            raise ValueError(f"Proposal {proposal_id!r} already registered")
        state = ProposalInteractionState(proposal_id=proposal_id)
        self._proposals[proposal_id] = state
        return state

    def get(self, proposal_id: str) -> ProposalInteractionState:
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal_id: {proposal_id!r}")
        return self._proposals[proposal_id]

    def proposal_ids(self) -> list[str]:
        return list(self._proposals.keys())

    def bulk_confirm_not_supported(self) -> None:
        """Explicit sentinel — calling confirm on multiple proposals requires
        individual calls to get(proposal_id).confirm() for each."""
        raise NotImplementedError(
            "Bulk confirmation is not supported. "
            "Call confirm() on each proposal individually."
        )

    def summary(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "proposal_count": len(self._proposals),
            "proposals": {pid: s.as_dict() for pid, s in self._proposals.items()},
        }
