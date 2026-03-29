"""Orchestrator runtime for Pilot Agent.

Entry point for event-driven execution of the promotion agent.
Handles event ingestion, graph execution, and emission.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.events.schema import OutboxEvent
from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.graph import run_promotion_graph
from app.agents.pilot_agent.events import state_to_event
from app.services.outbox import append_jsonl_outbox_event

logger = logging.getLogger(__name__)


async def run_promotion_agent(event: OutboxEvent) -> None:
    """Execute the Pilot Agent on a promotion intent event.

    Steps:
    1. Check feature flag (LANGGRAPH_PILOT_AGENT)
    2. Parse event → PilotAgentState
    3. Run graph via build_promotion_graph()
    4. Normalize state → Outbox event
    5. Emit to outbox
    6. Emit telemetry

    Args:
        event: Input Outbox event with promotion intent

    Note:
        Falls back to deterministic handler if feature flag is not "promotion"
    """
    # Feature flag check
    feature_flag = os.getenv("LANGGRAPH_PILOT_AGENT", "off").strip().lower()
    if feature_flag != "promotion":
        logger.debug(
            "Pilot agent disabled, falling back to deterministic",
            extra={"trace_id": event.trace_id},
        )
        await _deterministic_promotion_fallback(event)
        return

    trace_id = event.trace_id
    start_time = time.time()

    try:
        # Layer 1: Input normalization
        logger.debug(
            "Parsing event to state",
            extra={"trace_id": trace_id, "event": event.event},
        )
        state = PilotAgentState.from_event(event)

        # Layer 2: Run graph
        logger.debug(
            "Running promotion graph",
            extra={"trace_id": trace_id, "note_uuid": state.note_uuid},
        )
        final_state = run_promotion_graph(state)

        # Layer 4: Output normalization
        logger.debug(
            "Normalizing output",
            extra={"trace_id": trace_id, "decision": final_state.decision},
        )
        result_event = state_to_event(final_state, event_id=None)

        # Layer 5: Emit
        logger.debug(
            "Emitting result event",
            extra={"trace_id": trace_id, "result_event": result_event.event},
        )
        append_jsonl_outbox_event(None, result_event, default_source="pilot_agent")

        # Telemetry
        elapsed = time.time() - start_time
        logger.info(
            "promotion_agent completed",
            extra={
                "trace_id": trace_id,
                "decision": final_state.decision,
                "confidence": final_state.confidence,
                "steps": final_state.step_count,
                "elapsed_seconds": elapsed,
                "error": final_state.error,
            },
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "promotion_agent failed",
            extra={
                "trace_id": trace_id,
                "error": str(e),
                "elapsed_seconds": elapsed,
            },
        )
        # Emit error event
        error_state = PilotAgentState(
            trace_id=trace_id,
            note_uuid=str(event.payload.get("note_uuid", "")),
            error=str(e),
            decision="skip",
        )
        error_event = state_to_event(error_state, event_id=None)
        append_jsonl_outbox_event(None, error_event, default_source="pilot_agent")


async def _deterministic_promotion_fallback(event: OutboxEvent) -> None:
    """Fallback handler when LangGraph is disabled.

    Implements basic heuristic logic without LLM calls.

    Args:
        event: Input Outbox event
    """
    logger.debug(
        "Deterministic fallback active",
        extra={"trace_id": event.trace_id},
    )

    payload = event.payload or {}
    confidence = float(payload.get("confidence", 0.5))

    # Simple heuristic: high confidence → promote
    if confidence > 0.7:
        decision = "promote"
    elif confidence > 0.5:
        decision = "evergreen"
    else:
        decision = "skip"

    # Create result event
    state = PilotAgentState(
        trace_id=event.trace_id,
        note_uuid=str(payload.get("note_uuid", "")),
        decision=decision,
        confidence=confidence,
        reason="Deterministic fallback (LLM disabled)",
    )

    result_event = state_to_event(state, event_id=None)
    append_jsonl_outbox_event(None, result_event, default_source="pilot_agent")

    logger.info(
        "deterministic_promotion_completed",
        extra={
            "trace_id": event.trace_id,
            "decision": decision,
            "confidence": confidence,
        },
    )


__all__ = ["run_promotion_agent"]
