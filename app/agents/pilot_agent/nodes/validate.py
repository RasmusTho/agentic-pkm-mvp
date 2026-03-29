"""Validate node: Check state validity and initialize."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.pilot_agent.state import PilotAgentState

logger = logging.getLogger(__name__)


def validate_node(state: PilotAgentState) -> PilotAgentState:
    """Validate state and initialize if needed.

    Checks:
    - trace_id is present
    - note_uuid is present
    - budget is positive

    Returns:
        Updated state with step_count incremented
    """
    try:
        # Check trace_id
        if not state.trace_id or not isinstance(state.trace_id, str):
            return state.copy(update={"error": "Invalid or missing trace_id"})

        # Check note_uuid
        if not state.note_uuid or not isinstance(state.note_uuid, str):
            return state.copy(update={"error": "Invalid or missing note_uuid"})

        # Check budget
        if state.budget <= 0:
            return state.copy(update={"error": "Invalid budget (must be > 0)"})

        # Validation passed
        return state.copy(
            update={
                "step_count": state.step_count + 1,
                "executed_actions": state.executed_actions + ["validate"],
            }
        )

    except Exception as e:
        logger.error(
            "Validation failed",
            extra={"trace_id": state.trace_id, "error": str(e)},
        )
        return state.copy(update={"error": f"Validation error: {str(e)}"})


__all__ = ["validate_node"]
