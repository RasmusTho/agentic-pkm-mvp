from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from app.knowledge.write_ops import append_note_relative, write_note_relative
from app.services.note_uuid import ensure_note_uuid
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter


CHAT_SESSION_PERSIST_ACTION = "chat_session.persist"


@dataclass(frozen=True)
class SessionLog:
    log_path: Path
    session_id: str
    note_path: Path
    label: str
    vault_root: Path | None = None
    note_uuid: str | None = None


class SessionLogWriter:
    def __init__(
        self,
        *,
        vault_root: Path,
        now_fn: Callable[[], datetime] | None = None,
        uuid_fn: Callable[[], str] | None = None,
    ) -> None:
        self._vault_root = vault_root
        self._now_fn = now_fn or datetime.now
        self._uuid_fn = uuid_fn or (lambda: str(uuid4()))

    def open_session(self, note_path: Path, session_label: str) -> SessionLog:
        # This must precede UUID healing as well as the session write: healing a
        # legacy note can itself write frontmatter.
        DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION)
        note_uuid = ensure_note_uuid(note_path, vault_root=self._vault_root)
        now = self._now_fn()
        note_slug = _slugify(note_path.stem)
        label_slug = _slugify(session_label)
        ts_file = now.strftime("%Y-%m-%dT%H-%M")
        ts_frontmatter = now.strftime("%Y-%m-%dT%H:%M")
        session_id = self._uuid_fn()

        log_rel_path = Path(".chats") / note_slug / f"{ts_file}-{label_slug}.md"
        log_path = self._vault_root / log_rel_path

        note_title = note_path.stem
        frontmatter = (
            "---\n"
            "type: chat-session\n"
            f'note: "[[{note_title}]]"\n'
            f"note_uuid: {note_uuid}\n"
            f"date: {ts_frontmatter}\n"
            f"session_id: {session_id}\n"
            "---\n\n"
            f"## Session: {label_slug}\n\n"
        )
        write_note_relative(log_rel_path.as_posix(), frontmatter, vault_root=self._vault_root)
        return SessionLog(
            log_path=log_path,
            session_id=session_id,
            note_path=note_path,
            label=label_slug,
            vault_root=self._vault_root,
            note_uuid=note_uuid,
        )

    def append_turn(self, session: SessionLog, user_prompt: str, change_summary: str) -> None:
        DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION)
        append_note_relative(
            _session_log_relative_path(session),
            f"**User:** {user_prompt}\n**Change:** {change_summary}\n\n",
            vault_root=self._vault_root,
        )

    def close_session(self, session: SessionLog, total_summary: str) -> None:
        DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION)
        append_note_relative(
            _session_log_relative_path(session),
            f"---\n*Session closed. Total: {total_summary}.*\n",
            vault_root=self._vault_root,
        )


def load_chat_sessions_for_note(note_uuid: str, *, vault_context: VaultContext) -> list[SessionLog]:
    """Return durable chat sessions linked to ``note_uuid``.

    The query deliberately globs all chat directories rather than deriving a
    directory from the note title: chat directories are presentation slugs and
    can legitimately be stale after a note rename.
    """
    if not vault_context.active_vault_path:
        return []
    vault_root = Path(vault_context.active_vault_path).expanduser().resolve()
    sessions: list[SessionLog] = []
    for path in sorted((vault_root / ".chats").glob("**/*.md")):
        try:
            frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(frontmatter, dict) or str(frontmatter.get("note_uuid") or "") != note_uuid:
            continue
        session_id = str(frontmatter.get("session_id") or "").strip()
        if not session_id:
            continue
        note = str(frontmatter.get("note") or "").strip()
        note_title = note.removeprefix("[[").removesuffix("]]")
        sessions.append(
            SessionLog(
                log_path=path,
                session_id=session_id,
                note_path=Path(note_title),
                label=path.stem,
                vault_root=vault_root,
                note_uuid=note_uuid,
            )
        )
    return sessions


def _session_log_relative_path(session: SessionLog) -> str:
    vault_root = session.vault_root
    if vault_root is None:
        raise ValueError("SessionLog.vault_root is required for durable chat writes")
    return session.log_path.relative_to(vault_root).as_posix()


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = slug.strip("-")
    return slug or "session"


__all__ = [
    "CHAT_SESSION_PERSIST_ACTION",
    "SessionLog",
    "SessionLogWriter",
    "load_chat_sessions_for_note",
]
