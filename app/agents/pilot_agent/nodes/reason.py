"""Reason node: LLM-based reasoning about promotion decision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade

if TYPE_CHECKING:
    from app.agents.pilot_agent.state import PilotAgentState

logger = logging.getLogger(__name__)


def _build_reasoning_prompt(state: PilotAgentState) -> str:
    """Build a prompt for the LLM to reason about promotion."""
    note_uuid = getattr(state, "note_uuid", getattr(state, "uuid", ""))
    confidence = float(getattr(state, "confidence", 0.0) or 0.0)
    source_ref = getattr(state, "source_ref", "") or "N/A"
    return f"""Analyze the following note promotion request and provide your recommendation.

Note UUID: {note_uuid}
Current Confidence: {confidence:.2f}
Source Reference: {source_ref}

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

        prompt = _build_reasoning_prompt(state)
        messages = list(state.messages)
        messages.append({"role": "user", "content": prompt})

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["promote", "evergreen", "archive", "skip"],
                },
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["decision", "reasoning", "confidence"],
            "additionalProperties": False,
        }

        facade = get_reasoning_facade()
        response = facade.structured(
            messages,
            schema=schema,
            task_kind=ReasoningTaskKind.DECIDE.value,
            trace_id=state.trace_id,
        )

        # Parse response
        decision = str(response.get("decision", "skip"))
        reasoning = str(response.get("reasoning", ""))
        confidence = _coerce_confidence(response.get("confidence"))

        messages.append({"role": "assistant", "content": response})

        return _update_state(
            state,
            step_count=state.step_count + 1,
            reason=reasoning,
            decision=decision,
            confidence=confidence,
            messages=messages,
            executed_actions=state.executed_actions + ["reason"],
        )

    except Exception as e:
        logger.error(
            "Reasoning failed",
            extra={
                "trace_id": state.trace_id,
                "note_uuid": getattr(state, "note_uuid", getattr(state, "uuid", "")),
                "error": str(e),
            },
        )
        # Graceful fallback: mark as skip
        return _update_state(
            state,
            error=f"Reasoning error: {str(e)}",
            decision="skip",
            executed_actions=state.executed_actions + ["reason"],
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


def _coerce_confidence(value: Any) -> float:
    """Normalize confidence input to a bounded float."""
    try:
        confidence = float(value)
        return max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        return 0.5


def _update_state(state: PilotAgentState, **updates: Any) -> PilotAgentState:
    """Update either the app dataclass or the slimmer test harness dataclass."""
    copy_fn = getattr(state, "copy", None)
    if callable(copy_fn):
        try:
            return copy_fn(update=updates)
        except TypeError:
            pass
    for key, value in updates.items():
        setattr(state, key, value)
    return state


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
