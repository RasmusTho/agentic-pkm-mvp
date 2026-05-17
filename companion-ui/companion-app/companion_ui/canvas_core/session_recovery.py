"""Canvas Core paused-session recovery payload (#1030).

When a Canvas session is interrupted or paused, the session recovery module
captures the minimum payload needed for safe low-cost re-entry:
  - session and artifact identity,
  - last known body version hash (conflict detection marker),
  - pending edit count from the undo stack,
  - session log path for provenance continuity.

Recovery blocks new assistant body edits until the user has acknowledged
the re-entry state and any body conflict has been surfaced and resolved.

This module does NOT:
  - redefine session-log write timing (logs open at session start and append
    per turn; that contract lives in docs/CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS.md
    and app/chat/session_log.py),
  - silently merge external body changes during recovery,
  - make the session transcript canonical,
  - implement multi-note or workspace recovery,
  - implement Panel state recovery or bounded-suggestion recovery.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Body version marker
# ---------------------------------------------------------------------------


def _body_hash(body: str) -> str:
    """Return a short SHA-256 hex digest of the body text for conflict detection."""
    return hashlib.sha256(body.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Recovery payload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryPayload:
    """Minimum data needed to re-enter a paused or interrupted Canvas session.

    All fields are set at capture time (when the session enters paused/interrupted
    state) and are immutable.  body_version_hash is used to detect whether the
    active artifact body has changed externally during the interruption.
    """

    session_id: str
    artifact_id: str
    body_version_hash: str
    session_log_path: Path | None
    pending_edit_count: int


# ---------------------------------------------------------------------------
# Recovery status
# ---------------------------------------------------------------------------


class RecoveryStatus(str, Enum):
    """State of a paused/interrupted Canvas session re-entry."""

    NEEDS_REVIEW = "needs_review"
    CONFLICT_DETECTED = "conflict_detected"
    RECOVERED = "recovered"


# ---------------------------------------------------------------------------
# CanvasSessionRecovery
# ---------------------------------------------------------------------------


class CanvasSessionRecovery:
    """Manages the recovery payload for a paused or interrupted Canvas session.

    Usage:
        recovery = CanvasSessionRecovery()
        recovery.capture(
            session_id="s-001",
            artifact_id="note-abc",
            body="current body text",
            session_log_path=prov.session_log_path,
            applied_edit_count=len(undo_stack.applied_edits),
        )

        # When re-entering:
        status = recovery.check_for_conflict(current_body)
        if status == RecoveryStatus.CONFLICT_DETECTED:
            # surface conflict to user
            ...
        recovery.mark_recovered()
    """

    def __init__(self) -> None:
        self._payload: RecoveryPayload | None = None
        self._status: RecoveryStatus | None = None

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture(
        self,
        *,
        session_id: str,
        artifact_id: str,
        body: str,
        session_log_path: Path | None = None,
        applied_edit_count: int = 0,
    ) -> RecoveryPayload:
        """Capture recovery state at the moment the session enters paused/interrupted.

        The body_version_hash is computed from the body text at capture time.
        The session_log_path must be the path already opened by the provenance
        writer — recovery does not open a second log.

        Returns the captured payload for inspection.
        """
        payload = RecoveryPayload(
            session_id=session_id,
            artifact_id=artifact_id,
            body_version_hash=_body_hash(body),
            session_log_path=session_log_path,
            pending_edit_count=applied_edit_count,
        )
        self._payload = payload
        self._status = RecoveryStatus.NEEDS_REVIEW
        return payload

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def check_for_conflict(self, current_body: str) -> RecoveryStatus:
        """Compare the current artifact body to the captured version hash.

        If the body has changed externally (vault/Obsidian edit during interruption),
        transitions to CONFLICT_DETECTED rather than silently applying stale edits.

        Returns the resulting recovery status.  The caller is responsible for
        surfacing the conflict/review-needed state to the user before proceeding.

        Raises:
            RuntimeError: if capture() has not been called.
        """
        self._require_payload()
        assert self._payload is not None
        if _body_hash(current_body) != self._payload.body_version_hash:
            self._status = RecoveryStatus.CONFLICT_DETECTED
        return self._status  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Recovery completion
    # ------------------------------------------------------------------

    def mark_recovered(self) -> None:
        """Mark the session recovery as complete.

        After this call, blocks_new_edits returns False and the session
        may resume direct body co-authoring.

        Raises:
            RuntimeError: if capture() has not been called.
        """
        self._require_payload()
        self._status = RecoveryStatus.RECOVERED

    # ------------------------------------------------------------------
    # Read / inspect
    # ------------------------------------------------------------------

    @property
    def payload(self) -> RecoveryPayload | None:
        """The captured recovery payload; None if capture() has not been called."""
        return self._payload

    @property
    def recovery_status(self) -> RecoveryStatus | None:
        """Current recovery status; None if capture() has not been called."""
        return self._status

    @property
    def blocks_new_edits(self) -> bool:
        """True when recovery is pending and new assistant body edits must be blocked."""
        return self._status is not None and self._status != RecoveryStatus.RECOVERED

    @property
    def reentry_state(self) -> str:
        """Human-readable re-entry state for surface/UI display.

        Values:
          "not_captured"    — no interruption has been captured yet.
          "needs_review"    — interruption captured; user must acknowledge re-entry.
          "conflict_detected" — artifact body changed externally; user must review conflict.
          "recovered"       — recovery complete; normal co-authoring may resume.
        """
        if self._status is None:
            return "not_captured"
        return self._status.value

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_payload(self) -> None:
        if self._payload is None:
            raise RuntimeError(
                "No recovery payload captured. Call capture() first when the session "
                "enters paused or interrupted state."
            )


__all__ = [
    "CanvasSessionRecovery",
    "RecoveryPayload",
    "RecoveryStatus",
]
