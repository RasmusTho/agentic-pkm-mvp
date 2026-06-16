"""Canvas writer: in-place body editing for canvas Chat sessions.

Edits are authorized by the presence of an open session and applied
directly to the note body. Frontmatter is always preserved unchanged.
Governance-bearing mutations (frontmatter edits, cross-note writes)
are explicitly rejected and must use ``GovernanceRouter`` instead.

Writes route through ``app/knowledge/write_ops.py`` (KnowledgePort
boundary) — no direct file-system writes from this module.
"""

from __future__ import annotations

from pathlib import Path

from app.chat.session_log import SessionLog, SessionLogWriter
from app.knowledge.write_ops import write_note_from_absolute
from app.text.helpers import body_contains_frontmatter, split_frontmatter
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Private module-level aliases preserved for any same-module callers;
# cross-module consumers must import from app.text.helpers directly.
_body_contains_frontmatter = body_contains_frontmatter
_split_frontmatter = split_frontmatter


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class GovernanceBearingMutationError(Exception):
    """Raised when a canvas write would bypass the governance pipeline.

    Callers should route governance-bearing mutations (frontmatter edits,
    cross-note writes, lifecycle transitions) through ``GovernanceRouter``.
    """


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class CanvasWriter:
    """Apply in-place body edits to a note during an active canvas session.

    All writes route through ``app/knowledge/write_ops.write_note_from_absolute``
    (the KnowledgePort boundary). Frontmatter is separated before writing and
    reattached unchanged.

    Usage::

        lw = SessionLogWriter(vault_root=Path("vault"))
        cw = CanvasWriter(vault_root=Path("vault"), log_writer=lw)
        session = lw.open_session(note_path, "expand-context")
        cw.apply_edit(session, "New body content.", "added context section")
        lw.close_session(session, "one edit applied")
    """

    def __init__(
        self,
        vault_root: Path,
        log_writer: SessionLogWriter,
        *,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    ) -> None:
        self._vault_root = vault_root.resolve()
        self._log_writer = log_writer
        self._write_guard = write_guard

    def apply_edit(
        self,
        session: SessionLog | None,
        new_body: str,
        change_summary: str,
        *,
        user_prompt: str = "",
    ) -> None:
        """Replace the body of ``session.note_path`` with ``new_body``.

        Raises ``GovernanceBearingMutationError`` when:
        - ``session`` is ``None`` (no active session)
        - ``session.note_path`` is outside ``vault_root`` (cross-note/vault write)
        - ``new_body`` contains a frontmatter block (``---`` at start)

        Raises ``WritesBlockedError`` when the system write-guard is closed.
        """
        # Guard: open session required
        if session is None:
            raise GovernanceBearingMutationError(
                "No open session — canvas writes require an active session"
            )

        # Guard: respect the system-wide write lock. In-place body edits are
        # governed writes too — exactly like the governance path asserts in
        # ``GovernanceRouter`` — so a health/maintenance lock must block them (#1961).
        self._write_guard.assert_writes_allowed("canvas.coauthor.body_edit")

        # Guard: note path must be within vault_root (no cross-vault writes)
        note_abs = session.note_path.resolve()
        try:
            note_abs.relative_to(self._vault_root)
        except ValueError:
            raise GovernanceBearingMutationError(
                f"Cross-note write blocked: {session.note_path} is outside "
                f"vault root {self._vault_root}"
            )

        # Guard: new_body must not contain a frontmatter block
        if _body_contains_frontmatter(new_body):
            raise GovernanceBearingMutationError(
                "Frontmatter modification is governance-bearing — "
                "use GovernanceRouter for frontmatter changes"
            )

        # Read current note and split frontmatter from body
        current = session.note_path.read_text(encoding="utf-8")
        frontmatter_block, _ = _split_frontmatter(current)

        # Reassemble: original frontmatter + new body
        if frontmatter_block is not None:
            new_content = f"---{frontmatter_block}\n---\n{new_body}"
        else:
            new_content = new_body if new_body.endswith("\n") else new_body + "\n"

        # Write through KnowledgePort boundary
        write_note_from_absolute(note_abs, new_content, vault_root=self._vault_root)

        # Append a single provenance turn for this body edit.
        self._log_writer.append_turn(
            session,
            user_prompt=user_prompt,
            change_summary=change_summary,
        )


__all__ = ["CanvasWriter", "GovernanceBearingMutationError"]
