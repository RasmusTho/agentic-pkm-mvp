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


# The only edit class that is safe for the direct Canvas body-edit path.
# Any class not in this set is treated as governance-bearing or ambiguous and
# is rejected — this includes all named governance-bearing classes below and
# any future/unknown class (ambiguous-defaults-to-governance-bearing).
SAFE_EDIT_CLASSES: frozenset[str] = frozenset({"body"})

# Named mutation classes that are known to be governance-bearing.
# Used for documentation, testing, and routing classification.  Enforcement
# in apply_edit() uses SAFE_EDIT_CLASSES (allowlist), not this blocklist,
# so unrecognised classes are also blocked.
GOVERNANCE_BEARING_EDIT_CLASSES: frozenset[str] = frozenset(
    {
        "frontmatter",
        "classification",
        "cross_note",
        "lifecycle",
        "promotion",
        "commitment_state",
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
    - edit_class must be in SAFE_EDIT_CLASSES (allowlist — ambiguous classes blocked),
    - session, shell, and request must all refer to the same artifact.

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
            GovernanceBearingEditError: edit_class is not in SAFE_EDIT_CLASSES.
            ValueError: artifact_id mismatch between session, shell, or request.
        """
        session.assert_body_edit_allowed()

        if request.edit_class not in SAFE_EDIT_CLASSES:
            raise GovernanceBearingEditError(
                f"Edit class {request.edit_class!r} is not permitted on the Canvas direct "
                "body-edit path. Only 'body' edits may be applied in place. "
                "Route governance-bearing or ambiguous classes through the escape hatch."
            )

        if shell.artifact_id != session.artifact_id:
            raise ValueError(
                f"Shell artifact_id {shell.artifact_id!r} does not match "
                f"session artifact_id {session.artifact_id!r}. "
                "A Canvas session is bound to a single artifact."
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
    "SAFE_EDIT_CLASSES",
    "AppliedEdit",
    "BodyEditRequest",
    "CanvasBodyEditor",
    "GovernanceBearingEditError",
]
