"""Canvas Core direct body-edit apply path (#1026).

Direct in-place body editing is the default Canvas Core co-authoring posture.
Body edits apply during an active user-present Canvas session without pre-commit
approval.  Undo is the rollback mechanism.  Governance-bearing mutations are
blocked and must be routed through the escape hatch.

This module is NOT:
- Panel confirmation or Panel receipt generation.
- Canvas bounded suggestion flow apply path.
- Governance receipt production.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from companion_ui.canvas_core.active_artifact_shell import CanvasArtifactShell
from companion_ui.canvas_core.session_state import CanvasSessionState


# Mutation classes that are governance-bearing and must not pass through this path.
GOVERNANCE_BEARING_EDIT_CLASSES: frozenset[str] = frozenset(
    {
        "frontmatter",
        "cross_note",
        "lifecycle",
        "promotion",
        "companion_note",
        "receipt",
        "session_log",
        "system_artifact",
    }
)


class GovernanceBearingEditError(ValueError):
    """Raised when a governance-bearing mutation is attempted via the direct body-edit path.

    These must be routed through the governance-bearing escape hatch, not applied
    directly through Canvas Core body co-authoring.
    """


@dataclass
class BodyEditRequest:
    """A request to apply an assistant body edit to the active artifact."""

    artifact_id: str
    new_body: str
    edit_class: str = "body"
    edit_summary: str = ""
    user_prompt: str = ""


@dataclass
class AppliedEdit:
    """Record of an assistant body edit that was successfully applied.

    Carries enough metadata for undo (body_before/body_after) and session
    provenance (edit_summary, user_prompt, edit_id, session_id).
    """

    edit_id: str
    session_id: str
    artifact_id: str
    body_before: str
    body_after: str
    edit_summary: str
    user_prompt: str


class CanvasBodyEditor:
    """Applies assistant body edits directly to the active Canvas artifact shell.

    Enforces:
    - session must be active/user-present (delegated to CanvasSessionState),
    - edit_class must not be governance-bearing,
    - artifact_id must match the active shell.

    Does not produce Panel receipts or governance receipts.
    Does not implement undo execution (see undo_stack module).
    Does not write session provenance (see session_provenance module).
    """

    def apply_edit(
        self,
        shell: CanvasArtifactShell,
        session: CanvasSessionState,
        request: BodyEditRequest,
        *,
        session_id: str,
    ) -> AppliedEdit:
        """Apply a body edit and return the record needed for undo and provenance.

        Raises:
            PermissionError: session is not active/user-present.
            GovernanceBearingEditError: edit_class is governance-bearing.
            ValueError: artifact_id mismatch.
        """
        session.assert_body_edit_allowed()

        if request.edit_class in GOVERNANCE_BEARING_EDIT_CLASSES:
            raise GovernanceBearingEditError(
                f"Edit class {request.edit_class!r} is governance-bearing and must not "
                "be applied through the Canvas direct body-edit path. "
                "Route through the governance-bearing escape hatch instead."
            )

        if request.artifact_id != shell.artifact_id:
            raise ValueError(
                f"Edit artifact_id {request.artifact_id!r} does not match "
                f"active shell artifact_id {shell.artifact_id!r}."
            )

        body_before = shell.body
        shell.body = request.new_body

        return AppliedEdit(
            edit_id=str(uuid4()),
            session_id=session_id,
            artifact_id=request.artifact_id,
            body_before=body_before,
            body_after=request.new_body,
            edit_summary=request.edit_summary,
            user_prompt=request.user_prompt,
        )


__all__ = [
    "GOVERNANCE_BEARING_EDIT_CLASSES",
    "AppliedEdit",
    "BodyEditRequest",
    "CanvasBodyEditor",
    "GovernanceBearingEditError",
]
