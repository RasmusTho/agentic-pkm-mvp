"""Canvas Core session provenance write/read integration (#1028).

Session provenance is the append-only intent trail captured alongside the note
during an active Canvas session.  The note is the canonical artifact; provenance
is subordinate.

Provenance semantics (anchored to docs/CANVAS_CHAT_SURFACE/WRITE_SESSION_LOGS.md
and app/chat/session_log.py):
- Open at session start; do not defer until close.
- Append per edit/turn; do not rewrite prior content.
- Mark undone edits without deleting the original append.
- Expose session log path for read/inspection.
- Close at session close with a total summary.

This module defines a ProvenanceWriter protocol so Canvas Core does not take a
hard import dependency on app/chat.  Callers inject a SessionLogWriter (or any
compatible writer) at construction time.

This module is NOT:
- Panel receipt rendering.
- Governance execution receipt production.
- Retention policy enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from companion_ui.canvas_core.body_edit import AppliedEdit
from companion_ui.canvas_core.undo_stack import UndoneEdit


# ---------------------------------------------------------------------------
# ProvenanceWriter protocol — structurally compatible with SessionLogWriter.
# ---------------------------------------------------------------------------


class _ProvenanceSession(Protocol):
    """Structural match for app.chat.session_log.SessionLog."""

    log_path: Path
    session_id: str


class ProvenanceWriter(Protocol):
    """Structural protocol for session log writers.

    Matches the interface of app.chat.session_log.SessionLogWriter so a real
    SessionLogWriter can be injected without this module importing app/.
    """

    def open_session(self, note_path: Path, session_label: str) -> _ProvenanceSession:
        ...

    def append_turn(
        self, session: Any, user_prompt: str, change_summary: str
    ) -> None:
        ...

    def close_session(self, session: Any, total_summary: str) -> None:
        ...


# ---------------------------------------------------------------------------
# CanvasSessionProvenance — Canvas Core provenance coordinator.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceSummary:
    """Read-only snapshot of the active provenance state for inspection."""

    session_log_path: Path
    session_id: str
    is_open: bool


class CanvasSessionProvenance:
    """Manages session provenance for a single Canvas Core session.

    Usage:
        writer = SessionLogWriter(vault_root=vault_root)
        prov = CanvasSessionProvenance(
            writer=writer,
            note_path=Path("vault/notes/my-note.md"),
            session_label="editing-intro",
        )
        prov.open()                            # call at Canvas session start
        prov.record_edit(applied_edit)         # call after each body edit
        prov.record_undo(undone_edit)          # call after each undo
        prov.record_interruption("paused")     # call when session pauses/interrupts
        prov.close("Total: one intro edit")    # call at session close
        path = prov.session_log_path           # expose for inspection
    """

    def __init__(
        self,
        *,
        writer: ProvenanceWriter,
        note_path: Path,
        session_label: str,
    ) -> None:
        self._writer = writer
        self._note_path = note_path
        self._session_label = session_label
        self._session: _ProvenanceSession | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open/create the session log.  Must be called at Canvas session start."""
        if self._session is not None:
            raise RuntimeError("Provenance session is already open.")
        self._session = self._writer.open_session(self._note_path, self._session_label)
        self._closed = False

    def close(self, total_summary: str) -> None:
        """Close the session log with a total summary."""
        self._require_open()
        self._writer.close_session(self._session, total_summary)
        self._closed = True

    # ------------------------------------------------------------------
    # Append operations (during session)
    # ------------------------------------------------------------------

    def record_edit(self, edit: AppliedEdit) -> None:
        """Append an assistant-applied body edit entry to provenance."""
        self._require_open()
        summary = edit.edit_summary or "(body edit)"
        self._writer.append_turn(
            self._session,
            user_prompt=edit.user_prompt or "(assistant-initiated)",
            change_summary=f"[edit:{edit.edit_id}] {summary}",
        )

    def record_undo(self, undone: UndoneEdit) -> None:
        """Append an undo marker for a rolled-back edit without deleting history."""
        self._require_open()
        original_id = undone.original_edit.edit_id
        self._writer.append_turn(
            self._session,
            user_prompt="(undo)",
            change_summary=f"[undo:{undone.undo_id}] reverted edit:{original_id}",
        )

    def record_interruption(self, state: str) -> None:
        """Append an interruption marker when the session pauses or is interrupted."""
        self._require_open()
        self._writer.append_turn(
            self._session,
            user_prompt="(session interrupted)",
            change_summary=f"[session:{state}] provenance retained up to this point",
        )

    # ------------------------------------------------------------------
    # Read / inspect
    # ------------------------------------------------------------------

    @property
    def session_log_path(self) -> Path | None:
        """Path to the active session log file; None if not yet opened."""
        return self._session.log_path if self._session is not None else None

    @property
    def session_id(self) -> str | None:
        """Session ID assigned by the writer; None if not yet opened."""
        return self._session.session_id if self._session is not None else None

    @property
    def is_open(self) -> bool:
        return self._session is not None and not self._closed

    def summary(self) -> ProvenanceSummary | None:
        """Return a read-only snapshot for inspection; None if not yet opened."""
        if self._session is None:
            return None
        return ProvenanceSummary(
            session_log_path=self._session.log_path,
            session_id=self._session.session_id,
            is_open=self.is_open,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_open(self) -> None:
        if self._session is None:
            raise RuntimeError("Provenance session is not open. Call open() first.")
        if self._closed:
            raise RuntimeError("Provenance session is already closed.")


__all__ = [
    "CanvasSessionProvenance",
    "ProvenanceSummary",
    "ProvenanceWriter",
]
