from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class SessionLog:
    log_path: Path
    session_id: str
    note_path: Path
    label: str


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
        now = self._now_fn()
        note_slug = _slugify(note_path.stem)
        label_slug = _slugify(session_label)
        ts_file = now.strftime("%Y-%m-%dT%H-%M")
        ts_frontmatter = now.strftime("%Y-%m-%dT%H:%M")
        session_id = self._uuid_fn()

        session_dir = self._vault_root / ".chats" / note_slug
        session_dir.mkdir(parents=True, exist_ok=True)
        log_path = session_dir / f"{ts_file}-{label_slug}.md"

        note_title = note_path.stem
        frontmatter = (
            "---\n"
            "type: chat-session\n"
            f'note: "[[{note_title}]]"\n'
            f"date: {ts_frontmatter}\n"
            f"session_id: {session_id}\n"
            "---\n\n"
            f"## Session: {label_slug}\n\n"
        )
        log_path.write_text(frontmatter, encoding="utf-8")
        return SessionLog(log_path=log_path, session_id=session_id, note_path=note_path, label=label_slug)

    def append_turn(self, session: SessionLog, user_prompt: str, change_summary: str) -> None:
        with session.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"**User:** {user_prompt}\n")
            handle.write(f"**Change:** {change_summary}\n\n")

    def close_session(self, session: SessionLog, total_summary: str) -> None:
        with session.log_path.open("a", encoding="utf-8") as handle:
            handle.write("---\n")
            handle.write(f"*Session closed. Total: {total_summary}.*\n")


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = slug.strip("-")
    return slug or "session"


__all__ = ["SessionLog", "SessionLogWriter"]
