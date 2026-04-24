"""Governance router: canvas-to-Panel bridge for governance-bearing mutations.

Canvas sessions may request governance-bearing mutations (frontmatter changes,
maturity transitions, cross-note operations). These must NOT go through
``CanvasWriter``; they must enter the Panel admission pipeline with the full
write-guard, allowlist, and receipt-generation path intact.

This module provides ``GovernanceRouter`` as the positive complement to
``CanvasWriter``'s rejection guards: instead of just raising
``GovernanceBearingMutationError``, the canvas surface can route here to
create a Panel intent and record it as pending.

The note is **never** mutated directly by this module. Execution happens
later, through the normal Panel pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.chat.session_log import SessionLog, SessionLogWriter
from app.write_guard import DEFAULT_WRITE_GUARD


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class GovernanceActionType(str, Enum):
    """Governance action types recognised by the canvas-to-Panel bridge."""

    FRONTMATTER_UPDATE = "frontmatter_update"
    MATURITY_TRANSITION = "maturity_transition"
    NOTE_LIFECYCLE = "note_lifecycle"
    CROSS_NOTE = "cross_note"


@dataclass
class PendingAction:
    """Receipt returned when a governance action is successfully queued.

    ``intent_id`` links back to the Panel pipeline entry; the session log
    records this ID so the provenance trail is traceable.
    """

    intent_id: str
    session_id: str
    action_type: GovernanceActionType
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Pipeline Protocol (injectable for test isolation)
# ---------------------------------------------------------------------------

class PanelPipeline(Protocol):
    """Minimal interface the router needs from the Panel admission path."""

    def submit_intent(self, action_type: str, payload: dict, session_id: str) -> str:
        """Submit a governance intent. Returns the intent_id receipt."""
        ...


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class GovernanceRouter:
    """Route canvas-originated governance requests into the Panel pipeline.

    Usage::

        router = GovernanceRouter(
            panel_pipeline=my_pipeline,
            session_log_writer=log_writer,
        )
        pending = router.request_governance_action(
            session=session,
            action_type=GovernanceActionType.FRONTMATTER_UPDATE,
            payload={"field": "maturity", "value": "evergreen"},
        )
        # pending.intent_id links to the Panel entry
        # Note is NOT mutated — intent is queued for Panel admission

    The ``panel_pipeline`` and ``write_guard`` arguments are injectable so the
    router is fully testable without Postgres or a live Panel runtime.
    """

    def __init__(
        self,
        panel_pipeline: PanelPipeline,
        session_log_writer: SessionLogWriter,
        write_guard: Any = None,
    ) -> None:
        self._pipeline = panel_pipeline
        self._log_writer = session_log_writer
        self._write_guard = write_guard if write_guard is not None else DEFAULT_WRITE_GUARD

    def request_governance_action(
        self,
        session: SessionLog,
        action_type: GovernanceActionType,
        payload: dict[str, Any],
    ) -> PendingAction:
        """Queue a governance action in the Panel pipeline and return a receipt.

        Steps:
        1. Assert write-guard is open (raises ``WritesBlockedError`` if not).
        2. Submit the intent to the Panel pipeline — returns ``intent_id``.
        3. Append a pending-action record to the session log.
        4. Return ``PendingAction`` with the intent receipt.

        The note is **never** touched directly; callers must not assume the
        mutation has been applied.
        """
        # Step 1: write-guard check (respects system-wide lock)
        self._write_guard.assert_writes_allowed("canvas.governance_action")

        # Step 2: submit to Panel pipeline
        intent_id = self._pipeline.submit_intent(
            action_type=action_type.value,
            payload=payload,
            session_id=session.session_id,
        )

        # Step 3: record in session log as pending (not executed)
        pending_record = (
            f"Governance action pending: {action_type.value} "
            f"payload={payload} (intent: {intent_id})"
        )
        self._log_writer.append_turn(
            session,
            user_prompt="",
            change_summary=pending_record,
        )

        # Step 4: return receipt
        return PendingAction(
            intent_id=intent_id,
            session_id=session.session_id,
            action_type=action_type,
            payload=payload,
        )


__all__ = ["GovernanceActionType", "GovernanceRouter", "PanelPipeline", "PendingAction"]
