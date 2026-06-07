from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.events.schema import OutboxEvent


@dataclass
class PilotAgentState:
    """State container for Pilot Agent LangGraph execution.

    Framework-level fields:
    - trace_id: For telemetry chain
    - budget: Max LLM calls allowed
    - step_count: Track iterations
    - messages: For LLM conversation

    Domain-specific fields (Promotion):
    - note_uuid: The note being promoted
    - source_ref: Reference to source event
    - confidence: Confidence in decision (0.0-1.0)
    - reason: Explanation for decision
    - decision: promote | evergreen | archive | skip
    - executed_actions: List of actions taken
    - error: Error message if any occurred
    """

    # Framework
    trace_id: str
    note_uuid: str
    authority: dict[str, Any] | None = None
    authority_basis: str | None = "read-only"
    proposal_id: str | None = None
    receipt_event_id: str | None = None
    budget: int = 10
    step_count: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Domain (Promotion)
    source_ref: str = ""
    confidence: float = 0.0
    reason: str = ""
    decision: str = ""  # promote | evergreen | archive | skip
    executed_actions: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_event(cls, event: OutboxEvent) -> PilotAgentState:
        """Create state from an Outbox event.

        Expected event payload:
        - note_uuid: str (required)
        - source_ref: str (optional)
        - confidence: float (optional)
        """
        payload = event.payload or {}
        return cls(
            trace_id=event.trace_id,
            note_uuid=str(payload.get("note_uuid", "")),
            source_ref=str(payload.get("source_ref", "")),
            confidence=float(payload.get("confidence", 0.0)),
        )

    def copy(self, *, update: dict[str, Any] | None = None) -> PilotAgentState:
        """Create a new instance with updated fields.

        Args:
            update: Dictionary of field names to new values

        Returns:
            New PilotAgentState instance
        """
        if update is None:
            update = {}

        # Build kwargs with current values
        kwargs = {
            "trace_id": self.trace_id,
            "authority": dict(self.authority) if self.authority is not None else None,
            "authority_basis": self.authority_basis,
            "proposal_id": self.proposal_id,
            "receipt_event_id": self.receipt_event_id,
            "budget": self.budget,
            "step_count": self.step_count,
            "messages": list(self.messages),
            "note_uuid": self.note_uuid,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "reason": self.reason,
            "decision": self.decision,
            "executed_actions": list(self.executed_actions),
            "error": self.error,
        }

        # Apply updates
        kwargs.update(update)

        return PilotAgentState(**kwargs)


__all__ = ["PilotAgentState"]
