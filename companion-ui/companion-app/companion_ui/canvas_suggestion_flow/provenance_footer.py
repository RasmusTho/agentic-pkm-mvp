"""ProvenanceFooter UI model for the Canvas bounded suggestion flow (#874).

Displays backend/session-provided provenance fields and surfaces intent tokens
for the UI layer to dispatch.  This model is a pure display/intent model:

- It does NOT write files.
- It does NOT call SessionLogWriter, WriteGuard, GovernanceRouter, or any
  vault/runtime writer.
- It does NOT compute inverse patches.
- It does NOT append body_edit_undone to the session log.
- It does NOT open files in Obsidian directly.
- It does NOT derive authoritative session history.

The footer dispatches exactly two intent tokens:
  provenance.openSessionLog  — hands off to the application intent mechanism to
                               open the .chats/... note in Obsidian.
  canvas.undoLastEdit        — dispatches an undo intent for the active session's
                               last applied body edit; backend handles the actual
                               inverse-patch computation and application.

Cross-session undo MUST NOT be dispatched by this footer.  The model captures
whether undo is available via can_undo_last_body_edit supplied by the caller.

Conceptual links (string references only, no import coupling):
  SuggestionCard    — the card whose suggestion was applied triggering a body edit.
  SuggestedInsertion — the in-document preview marker for the body edit.
  ReceiptPill       — the receipt displayed after a governance queue event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Intent tokens dispatched by the footer (read-only references, not routers).
INTENT_OPEN_SESSION_LOG = "provenance.openSessionLog"
INTENT_UNDO_LAST_EDIT = "canvas.undoLastEdit"


@dataclass
class ProvenanceFooter:
    """Render model for the ProvenanceFooter UI component.

    All fields are supplied by the backend/session context.  The footer renders
    and dispatches intents; it owns no runtime truth.

    Fields
    ------
    suggestion_id          ID of the paired suggestion (string reference only).
    artifact_id            ID of the artifact being edited (string reference).
    source_summary         Human-readable summary of the provenance source,
                           e.g. ".chats/<note-slug>/<timestamp>.md".
    route_summary          Human-readable summary of the route, e.g. "canvas direct body edit".
    receipt_id             Optional receipt ID if a governance receipt was produced.
    session_ref            Optional session reference string (e.g. session slug or ID).
    session_log_path       Path supplied by backend/session context for the session log.
                           MUST NOT be hardcoded.  None means unavailable.
    turn_count             Number of turns in the session, supplied by session state.
    can_undo_last_body_edit Whether the undo button should be enabled.
    last_body_edit_id      Optional ID of the last applied body edit (for undo intent context).
    """

    suggestion_id: str
    artifact_id: str
    source_summary: str
    route_summary: str
    receipt_id: Optional[str] = None
    session_ref: Optional[str] = None
    session_log_path: Optional[str] = None
    turn_count: int = 0
    can_undo_last_body_edit: bool = False
    last_body_edit_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.suggestion_id:
            raise ValueError("suggestion_id is required")
        if not self.artifact_id:
            raise ValueError("artifact_id is required")
        if not self.source_summary:
            raise ValueError("source_summary is required")
        if not self.route_summary:
            raise ValueError("route_summary is required")
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")

    @property
    def undo_intent(self) -> Optional[dict]:
        """The undo intent payload when undo is available, or None.

        Returns None when can_undo_last_body_edit is False, ensuring the
        footer cannot dispatch cross-session or unavailable undo intents.
        """
        if not self.can_undo_last_body_edit:
            return None
        return {
            "intent": INTENT_UNDO_LAST_EDIT,
            "session_ref": self.session_ref,
            "last_body_edit_id": self.last_body_edit_id,
        }

    @property
    def open_session_log_intent(self) -> Optional[dict]:
        """The open-session-log intent payload when a path is available, or None."""
        if not self.session_log_path:
            return None
        return {
            "intent": INTENT_OPEN_SESSION_LOG,
            "session_log_path": self.session_log_path,
        }

    def to_render_dict(self) -> dict:
        """Serialisable dict for the UI layer.

        Maps to the ProvenanceFooter HTML element defined in issue #874:
          data-testid="provenance-footer"
          aria-label="Session provenance"

        The undo button is disabled when can_undo_last_body_edit is False.
        The session log path button is disabled when session_log_path is None.

        This dict carries no runtime write operations.
        """
        d: dict = {
            "data_testid": "provenance-footer",
            "aria_label": "Session provenance",
            "suggestion_id": self.suggestion_id,
            "artifact_id": self.artifact_id,
            "source_summary": self.source_summary,
            "route_summary": self.route_summary,
            "turn_count": self.turn_count,
            # Session log path button
            "session_log_path": self.session_log_path,
            "session_log_button_disabled": self.session_log_path is None,
            "open_session_log_intent": INTENT_OPEN_SESSION_LOG,
            "open_session_log_intent_payload": self.open_session_log_intent,
            # Undo button
            "undo_button_disabled": not self.can_undo_last_body_edit,
            "undo_intent": INTENT_UNDO_LAST_EDIT,
            "undo_intent_payload": self.undo_intent,
            "data_testid_undo": "undo-last-edit",
        }
        if self.receipt_id is not None:
            d["receipt_id"] = self.receipt_id
        if self.session_ref is not None:
            d["session_ref"] = self.session_ref
        if self.last_body_edit_id is not None:
            d["last_body_edit_id"] = self.last_body_edit_id
        return d
