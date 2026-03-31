"""Reason node: LLM-based reasoning about promotion decision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.components.llm.fabric import get_chat_client, LLMTaskIntent

if TYPE_CHECKING:
    from app.agents.pilot_agent.state import PilotAgentState

logger = logging.getLogger(__name__)


def _build_reasoning_prompt(state: PilotAgentState) -> str:
    """Build a prompt for the LLM to reason about promotion."""
    return f"""Analyze the following note promotion request and provide your recommendation.

Note UUID: {state.note_uuid}
Current Confidence: {state.confidence:.2f}
Source Reference: {state.source_ref or 'N/A'}

Based on typical promotion criteria (relevance, completeness, maturity), should this note be:
1. promoted - Move to a more permanent/visible location
2. evergreen - Keep in current location but mark as evergreen
3. archive - Move to archive due to age or relevance decline
4. skip - Leave unchanged

Provide your recommendation in the format:
DECISION: [promote|evergreen|archive|skip]
REASONING: [Your explanation]
CONFIDENCE: [0.0-1.0]
"""


def reason_node(state: PilotAgentState) -> PilotAgentState:
    """LLM-based reasoning about promotion decision.

    Uses the shared LLM fabric for decision-making.

    Returns:
        Updated state with reasoning and decision
    """
    try:
        # Skip if already in error state
        if state.error:
            return state

        # Check budget
        if state.step_count >= state.budget:
            return state.copy(
                update={
                    "error": "Budget exhausted",
                    "decision": "skip",
                }
            )

        # Build prompt
        prompt = _build_reasoning_prompt(state)

        # Call LLM via fabric
        client = get_chat_client(LLMTaskIntent(task_kind="reason", risk="high"))
        pack = {
            "messages": state.messages + [{"role": "user", "content": prompt}],
            "note_uuid": state.note_uuid,
        }

        response = client.chat(
            "pilot_agent_reason",
            pack,
            agent="pilot_agent",
            kind="reason",
            trace_id=state.trace_id,
        )

        # Parse response
        decision = _parse_decision(response)
        reasoning = _parse_reasoning(response)
        confidence = _parse_confidence(response)

        # Update state
        messages = list(state.messages)
        messages.append({"role": "assistant", "content": response})

        return state.copy(
            update={
                "step_count": state.step_count + 1,
                "reason": reasoning,
                "decision": decision,
                "confidence": confidence,
                "messages": messages,
                "executed_actions": state.executed_actions + ["reason"],
            }
        )

    except Exception as e:
        logger.error(
            "Reasoning failed",
            extra={
                "trace_id": state.trace_id,
                "note_uuid": state.note_uuid,
                "error": str(e),
            },
        )
        # Graceful fallback: mark as skip
        return state.copy(
            update={
                "error": f"Reasoning error: {str(e)}",
                "decision": "skip",
                "executed_actions": state.executed_actions + ["reason"],
            }
        )


def _parse_decision(response: str) -> str:
    """Extract decision from LLM response."""
    response_upper = response.upper()
    if "PROMOTE" in response_upper and "DECISION:" in response_upper:
        if "PROMOTE" in response_upper.split("DECISION:")[-1].split("\n")[0]:
            return "promote"
    if "EVERGREEN" in response_upper:
        return "evergreen"
    if "ARCHIVE" in response_upper:
        return "archive"
    return "skip"


def _parse_reasoning(response: str) -> str:
    """Extract reasoning from LLM response."""
    lines = response.split("\n")
    for i, line in enumerate(lines):
        if "REASONING:" in line.upper():
            # Get everything after REASONING: up to next field or end
            rest = line.split(":", 1)[-1].strip()
            if rest:
                return rest
            # Try next line
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    # Fallback: return first non-empty line
    for line in lines:
        stripped = line.strip()
        if stripped and not any(
            keyword in stripped.upper() for keyword in ["DECISION:", "CONFIDENCE:"]
        ):
            return stripped
    return response[:200]  # First 200 chars


def _parse_confidence(response: str) -> float:
    """Extract confidence score from LLM response."""
    try:
        lines = response.split("\n")
        for line in lines:
            if "CONFIDENCE:" in line.upper():
                # Extract number after CONFIDENCE:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    value_str = parts[1].strip()
                    # Try to extract float
                    for char in value_str:
                        if char not in "0123456789.":
                            value_str = value_str[: value_str.index(char)]
                            break
                    confidence = float(value_str)
                    return max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
    except (ValueError, IndexError, AttributeError):
        pass
    return 0.5  # Default


__all__ = ["reason_node"]
