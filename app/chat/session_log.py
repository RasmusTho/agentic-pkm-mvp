"""Session log writer for canvas Chat sessions.

Every canvas session produces an append-only provenance artifact under
``vault/.chats/<note-slug>/`` with ``type: chat-session`` frontmatter.

This module is pure file-system: no DB, no Docker required.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SessionLog:
    """A single canvas session's log file handle."""

    session_id: str
    note_path: Path
    log_path: Path
    label: str
    closed: bool = field(default=False)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class SessionLogWriter:
    """Write append-only session logs for canvas Chat sessions.

    Usage::

        writer = SessionLogWriter(vault_root=Path("vault"))
        session = writer.open_session(
            note_path=Path("vault/notes/my-note.md"),
            session_label="restructure-decision-section",
        )
        writer.append_turn(session, "Can you move the rationale?", "Moved rationale")
        writer.close_session(session, "One structural edit applied")
    """

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_session(self, note_path: Path, session_label: str) -> SessionLog:
        """Create the session log file and return a :class:`SessionLog` handle.

        The log is written to::

            <vault_root>/.chats/<note-slug>/<timestamp>-<label>.md

        Frontmatter fields: ``type``, ``note``, ``date``, ``session_id``.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        slug = _note_slug(note_path)
        timestamp = _timestamp_for_path(now)
        safe_label = _safe_label(session_label)

        log_dir = self._vault_root / ".chats" / slug
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{timestamp}-{safe_label}.md"

        note_title = note_path.stem
        date_iso = now.strftime("%Y-%m-%dT%H:%M")

        frontmatter = (
            "---\n"
            f"type: chat-session\n"
            f'note: "[[{note_title}]]"\n'
            f"date: {date_iso}\n"
            f"session_id: {session_id}\n"
            "---\n"
            "\n"
            f"## Session: {session_label}\n"
            "\n"
        )
        log_path.write_text(frontmatter, encoding="utf-8")

        return SessionLog(
            session_id=session_id,
            note_path=note_path,
            log_path=log_path,
            label=session_label,
        )

    def append_turn(
        self,
        session: SessionLog,
        user_prompt: str,
        change_summary: str,
    ) -> None:
        """Append one turn (user prompt + change summary) to the session log.

        Appends are strictly additive — prior content is never rewritten.
        """
        turn = (
            f"**User:** {user_prompt}\n"
            f"**Change:** {change_summary}\n"
            "\n"
        )
        with session.log_path.open("a", encoding="utf-8") as fh:
            fh.write(turn)

    def close_session(self, session: SessionLog, total_summary: str) -> None:
        """Append a final closure line and mark the session as closed."""
        closure = f"---\n*Session closed. Total: {total_summary}*\n"
        with session.log_path.open("a", encoding="utf-8") as fh:
            fh.write(closure)
        session.closed = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _note_slug(note_path: Path) -> str:
    """Derive a filesystem-safe slug from the note filename.

    Lowercased, spaces and underscores replaced with hyphens, other
    non-alphanumeric characters stripped.
    """
    stem = note_path.stem
    slug = stem.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "note"


def _timestamp_for_path(dt: datetime) -> str:
    """ISO-8601 timestamp with colons replaced by hyphens for filesystem use.

    Example: ``2026-04-22T14-30``
    """
    return dt.strftime("%Y-%m-%dT%H-%M")


def _safe_label(label: str) -> str:
    """Normalise a session label to a filesystem-safe hyphenated string."""
    label = label.lower()
    label = re.sub(r"[\s_]+", "-", label)
    label = re.sub(r"[^a-z0-9\-]", "", label)
    label = re.sub(r"-{2,}", "-", label).strip("-")
    return label or "session"


__all__ = ["SessionLog", "SessionLogWriter"]
