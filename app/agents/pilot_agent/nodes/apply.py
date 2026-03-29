"""Apply node: Finalize decision and set state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.pilot_agent.state import PilotAgentState

logger = logging.getLogger(__name__)


def apply_node(state: PilotAgentState) -> PilotAgentState:
    """Apply the decision and finalize state.

    Sets final decision if not already set, normalizes confidence,
    and prepares state for emission.

    Returns:
        Final state ready for output normalization
    """
    try:
        # Normalize confidence first (always)
        confidence = max(0.0, min(1.0, state.confidence))

        # Skip if in error state but decision already set
        if state.error and state.decision:
            valid_decisions = {"promote", "evergreen", "archive", "skip"}
            decision = state.decision if state.decision in valid_decisions else "skip"
            return state.copy(
                update={
                    "decision": decision,
                    "confidence": confidence,
                    "step_count": state.step_count + 1,
                    "executed_actions": state.executed_actions + ["apply"],
                }
            )

        # If in error state with no decision, default to skip
        if state.error and not state.decision:
            return state.copy(
                update={
                    "decision": "skip",
                    "confidence": 0.0,
                    "step_count": state.step_count + 1,
                    "executed_actions": state.executed_actions + ["apply"],
                }
            )

        # Ensure decision is valid
        valid_decisions = {"promote", "evergreen", "archive", "skip"}
        if state.decision not in valid_decisions:
            decision = state.decision or "skip"
            if decision not in valid_decisions:
                decision = "skip"

            return state.copy(
                update={
                    "decision": decision,
                    "confidence": confidence,
                    "step_count": state.step_count + 1,
                    "executed_actions": state.executed_actions + ["apply"],
                }
            )

        return state.copy(
            update={
                "confidence": confidence,
                "step_count": state.step_count + 1,
                "executed_actions": state.executed_actions + ["apply"],
            }
        )

    except Exception as e:
        logger.error(
            "Apply failed",
            extra={"trace_id": state.trace_id, "note_uuid": state.note_uuid},
        )
        return state.copy(
            update={
                "error": f"Apply error: {str(e)}",
                "decision": state.decision or "skip",
                "confidence": max(0.0, min(1.0, state.confidence)),
                "step_count": state.step_count + 1,
                "executed_actions": state.executed_actions + ["apply"],
            }
        )


__all__ = ["apply_node"]
