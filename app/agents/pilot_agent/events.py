"""Event schemas for Pilot Agent."""

from __future__ import annotations

from typing import Any

from app.events.schema import OutboxEvent
from app.agents.pilot_agent.state import PilotAgentState


# Input events
PROMOTION_INTENT_CREATED = "promotion.intent.created"

# Output events
PROMOTION_APPROVED = "promotion.approved"
PROMOTION_DEFERRED = "promotion.deferred"
PROMOTION_SKIPPED = "promotion.skipped"
PROMOTION_ARCHIVED = "promotion.archived"


def state_to_event(state: PilotAgentState, event_id: str | None = None) -> OutboxEvent:
    """Convert agent state to emittable Outbox event.

    Args:
        state: Final agent state
        event_id: Optional event ID (will be auto-generated if None)

    Returns:
        OutboxEvent ready for emission
    """
    from uuid import uuid4

    # Map decision to event type
    decision_to_event = {
        "promote": PROMOTION_APPROVED,
        "evergreen": PROMOTION_DEFERRED,
        "archive": PROMOTION_ARCHIVED,
        "skip": PROMOTION_SKIPPED,
    }

    event_type = decision_to_event.get(state.decision, PROMOTION_SKIPPED)

    payload = {
        "note_uuid": state.note_uuid,
        "decision": state.decision or "skip",
        "reasoning": state.reason,
        "confidence": state.confidence,
        "steps": state.step_count,
    }

    if state.error:
        payload["error"] = state.error

    meta: dict[str, Any] = {
        "telemetry": {
            "steps": state.step_count,
            "budget_remaining": state.budget - state.step_count,
            "executed_actions": state.executed_actions,
        }
    }

    if state.error:
        meta["telemetry"]["error"] = state.error

    # Create event directly to support custom event_id
    return OutboxEvent(
        event=event_type,
        event_id=event_id or uuid4().hex,
        trace_id=state.trace_id,
        source="pilot_agent",
        payload=payload,
        meta=meta,
    )


__all__ = [
    "PROMOTION_INTENT_CREATED",
    "PROMOTION_APPROVED",
    "PROMOTION_DEFERRED",
    "PROMOTION_SKIPPED",
    "PROMOTION_ARCHIVED",
    "state_to_event",
]
