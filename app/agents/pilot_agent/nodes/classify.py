"""Classify node: Determine note type and action appropriateness."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.pilot_agent.state import PilotAgentState

logger = logging.getLogger(__name__)


def classify_node(state: PilotAgentState) -> PilotAgentState:
    """Classify note type and check action appropriateness.

    In a production system, this would:
    - Retrieve note metadata
    - Analyze note type/category
    - Check if promotion is appropriate

    For now, uses heuristics based on state.

    Returns:
        Updated state with classification complete
    """
    try:
        # Skip if already in error state
        if state.error:
            return state

        # Add classification message to context
        messages = list(state.messages)
        messages.append(
            {
                "role": "system",
                "content": (
                    "You are a note promotion classifier. "
                    "Analyze whether a note should be promoted based on its type and content."
                ),
            }
        )

        return state.copy(
            update={
                "step_count": state.step_count + 1,
                "messages": messages,
                "executed_actions": state.executed_actions + ["classify"],
            }
        )

    except Exception as e:
        logger.error(
            "Classification failed",
            extra={"trace_id": state.trace_id, "note_uuid": state.note_uuid},
        )
        return state.copy(update={"error": f"Classification error: {str(e)}"})


__all__ = ["classify_node"]
