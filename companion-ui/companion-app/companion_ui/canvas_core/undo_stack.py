"""Canvas Core undo stack for assistant-applied body edits (#1027).

Undo is the rollback path for direct body co-authoring edits.  The stack is
scoped to a single session and a single artifact.  Provenance markers are
preserved — undo does not delete history.

This module is NOT:
- Panel rejection or confirmation.
- Canvas bounded suggestion discard.
- Governance execution rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
from companion_ui.canvas_core.body_edit import AppliedEdit


class UndoDivergenceError(RuntimeError):
    """Raised when undo cannot safely revert because the body has diverged.

    The body has changed since the assistant edit was applied (e.g., a user
    keystroke landed after the edit).  Silently overwriting user work is
    unsafe; the caller must surface this as a conflict before proceeding.
    """


@dataclass
class UndoneEdit:
    """Provenance record for a rolled-back assistant body edit.

    Preserved in the undo stack's undone list so provenance is never erased.
    """

    undo_id: str
    session_id: str
    artifact_id: str
    original_edit: AppliedEdit


class CanvasUndoStack:
    """Session-scoped, artifact-scoped undo stack for assistant-applied body edits.

    Design invariants:
    - push() validates session_id and artifact_id match the stack's scope.
    - undo() reverts the shell body and records an UndoneEdit for provenance.
    - Undone edits are retained in undone_edits; history is never deleted.
    - Cross-session and cross-artifact undo are explicitly blocked.
    """

    def __init__(self, *, session_id: str, artifact_id: str) -> None:
        self._session_id = session_id
        self._artifact_id = artifact_id
        self._applied: list[AppliedEdit] = []
        self._undone: list[UndoneEdit] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def artifact_id(self) -> str:
        return self._artifact_id

    @property
    def can_undo(self) -> bool:
        return bool(self._applied)

    @property
    def applied_edits(self) -> list[AppliedEdit]:
        return list(self._applied)

    @property
    def undone_edits(self) -> list[UndoneEdit]:
        return list(self._undone)

    def push(self, edit: AppliedEdit) -> None:
        """Record an applied edit so it can be undone later.

        Raises:
            ValueError: edit session_id or artifact_id does not match stack scope.
        """
        if edit.session_id != self._session_id:
            raise ValueError(
                f"Edit session_id {edit.session_id!r} does not match "
                f"stack session_id {self._session_id!r}. Undo is session-scoped."
            )
        if edit.artifact_id != self._artifact_id:
            raise ValueError(
                f"Edit artifact_id {edit.artifact_id!r} does not match "
                f"stack artifact_id {self._artifact_id!r}. Undo is artifact-scoped."
            )
        self._applied.append(edit)

    def undo(self, shell: CanvasArtifactShell) -> UndoneEdit:
        """Undo the most recent assistant-applied body edit.

        Reverts shell.body to the state before the edit and records an UndoneEdit
        for provenance.  The original AppliedEdit remains visible in undone_edits.

        Raises:
            IndexError: nothing to undo.
            ValueError: shell artifact_id does not match stack scope.
            UndoDivergenceError: the body has changed since the edit was applied
                (e.g., an intervening user keystroke); reverts the pop so the
                edit remains on the stack and the caller can surface the conflict.
        """
        if not self._applied:
            raise IndexError("Nothing to undo: the Canvas undo stack is empty.")
        if shell.artifact_id != self._artifact_id:
            raise ValueError(
                f"Shell artifact_id {shell.artifact_id!r} does not match "
                f"stack artifact_id {self._artifact_id!r}."
            )
        edit = self._applied.pop()
        if shell.body != edit.body_after:
            self._applied.append(edit)
            raise UndoDivergenceError(
                f"Cannot undo edit {edit.edit_id!r}: the current body differs from the "
                "body after the assistant edit was applied. An intervening change (e.g., "
                "a user keystroke) may have landed. Surface this as a conflict before "
                "proceeding with undo."
            )
        shell.body = edit.body_before
        undone = UndoneEdit(
            undo_id=str(uuid4()),
            session_id=self._session_id,
            artifact_id=self._artifact_id,
            original_edit=edit,
        )
        self._undone.append(undone)
        return undone


__all__ = ["CanvasUndoStack", "UndoDivergenceError", "UndoneEdit"]
