from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
import os
from pathlib import Path
import re
import stat
import threading
from typing import Callable
from typing import Iterator
from uuid import uuid4

from app.journaling.transcript_protocol import ROLE_MESSAGE_FORMAT_BLOCKQUOTE_V1
from app.knowledge.write_ops import append_note_relative, write_note_relative
from app.services.note_uuid import ensure_note_uuid
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter


CHAT_SESSION_PERSIST_ACTION = "chat_session.persist"
_SESSION_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS: dict[str, threading.RLock] = {}


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
        # Keep the standard-library basename sanitizer visible at the path
        # construction boundary. ``_slugify`` already removes separators, but
        # this explicit fence also lets static analysis prove that owner input
        # cannot control a path outside the generated chat namespace.
        note_slug = os.path.basename(_slugify(note_path.stem))
        label_slug = os.path.basename(_slugify(session_label))
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
            f"role_message_format: {ROLE_MESSAGE_FORMAT_BLOCKQUOTE_V1}\n"
            "---\n\n"
            f"## Session: {label_slug}\n\n"
        )
        receipt = write_note_relative(
            log_rel_path.as_posix(),
            frontmatter,
            vault_root=self._vault_root,
            action=CHAT_SESSION_PERSIST_ACTION,
            write_guard=DEFAULT_WRITE_GUARD,
            writer_identity="chat.session_log",
            create_once=True,
        )
        if receipt.outcome == "already_exists":
            try:
                existing_frontmatter, _ = load_frontmatter(
                    _read_existing_session_at(
                        log_rel_path,
                        vault_root=self._vault_root,
                    )
                )
            except OSError as exc:
                raise ValueError(
                    "chat session create-once target disappeared after publication"
                ) from exc
            existing_session_id = existing_frontmatter.get("session_id")
            existing_note_uuid = existing_frontmatter.get("note_uuid")
            if (
                existing_frontmatter.get("type") != "chat-session"
                or not isinstance(existing_session_id, str)
                or not existing_session_id.strip()
                or existing_note_uuid != note_uuid
            ):
                raise ValueError(
                    "chat session path is occupied by a different artifact: "
                    f"{log_rel_path.as_posix()}"
                )
            session_id = existing_session_id.strip()
        return SessionLog(
            log_path=log_path,
            session_id=session_id,
            note_path=note_path,
            label=label_slug,
            vault_root=self._vault_root,
            note_uuid=note_uuid,
        )

    def append_turn(self, session: SessionLog, user_prompt: str, change_summary: str) -> None:
        _append_to_open_session(
            session,
            f"**User:** {user_prompt}\n**Change:** {change_summary}\n\n",
        )

    def append_message(self, session: SessionLog, role: str, content: str) -> None:
        """Append one conversational message to the existing chat artifact.

        Canvas turns retain their historical ``User``/``Change`` shape through
        :meth:`append_turn`; non-editing chat flows can use explicit speaker
        roles without inventing another session transport or artifact class.
        """
        normalized_role = role.strip().lower()
        labels = {"agent": "Agent", "owner": "Owner"}
        if normalized_role not in labels:
            raise ValueError("chat message role must be 'agent' or 'owner'")
        normalized_content = (
            content.strip().replace("\r\n", "\n").replace("\r", "\n")
        )
        if not normalized_content:
            raise ValueError("chat message content must not be empty")
        quoted_content = "\n".join(
            f"> {line}" if line else ">"
            for line in normalized_content.split("\n")
        )
        _append_to_open_session(
            session,
            f"**{labels[normalized_role]}:**\n{quoted_content}\n\n",
        )

    def close_session(self, session: SessionLog, total_summary: str) -> None:
        normalized_summary = (
            total_summary.strip().replace("\r\n", "\n").replace("\r", "\n")
        )
        if not normalized_summary:
            raise ValueError("chat session summary must not be empty")
        quoted_summary = "\n".join(
            f"> {line}" if line else ">"
            for line in normalized_summary.split("\n")
        )
        _append_to_open_session(
            session,
            f"**Session closed:**\n{quoted_summary}\n\n",
        )


def _append_to_open_session(session: SessionLog, content: str) -> None:
    vault_root = session.vault_root
    if vault_root is None:
        raise ValueError("SessionLog.vault_root is required for durable chat writes")
    DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION)
    with _locked_session_writer(session):
        try:
            current = session.log_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError("chat session transcript no longer exists") from exc
        if (
            "\n**Session closed:**\n" in current
            or "\n*Session closed. Total: " in current
        ):
            raise ValueError("chat session is already closed")
        append_note_relative(
            _session_log_relative_path(session),
            content,
            vault_root=vault_root,
            action=CHAT_SESSION_PERSIST_ACTION,
            write_guard=DEFAULT_WRITE_GUARD,
        )


@contextmanager
def _locked_session_writer(session: SessionLog) -> Iterator[None]:
    vault_root = session.vault_root
    if vault_root is None:
        raise ValueError("SessionLog.vault_root is required for durable chat writes")
    resolved_root = vault_root.expanduser().resolve()
    resolved_log = session.log_path.expanduser().resolve()
    try:
        resolved_log.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("chat session transcript escapes the active vault") from exc
    lock_path = resolved_log.parent / f".{resolved_log.name}.session.lock"
    lock_key = str(lock_path)
    with _SESSION_LOCKS_GUARD:
        process_lock = _SESSION_LOCKS.setdefault(lock_key, threading.RLock())
    with process_lock:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            opened = os.fstat(descriptor)
            named = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise ValueError("chat session lock path is not a stable regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


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


def _read_existing_session_at(relative_path: Path, *, vault_root: Path) -> str:
    """Read one stable regular session file through its anchored vault path."""

    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError("chat session path must stay inside the active vault")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    resolved_root = vault_root.expanduser().resolve()
    descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        root_descriptor = os.open(resolved_root, directory_flags)
        descriptors.append(root_descriptor)
        for component in relative_path.parts[:-1]:
            child_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=descriptors[-1],
            )
            descriptors.append(child_descriptor)

        filename = relative_path.parts[-1]
        file_descriptor = os.open(
            filename,
            file_flags,
            dir_fd=descriptors[-1],
        )
        opened = os.fstat(file_descriptor)
        named = os.stat(filename, dir_fd=descriptors[-1], follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise ValueError("chat session target is not one stable regular file")

        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(file_descriptor)
        named_after = os.stat(
            filename,
            dir_fd=descriptors[-1],
            follow_symlinks=False,
        )
        if (
            (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            or (named_after.st_dev, named_after.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("chat session target changed while it was read")

        for parent_descriptor, component, child_descriptor in zip(
            descriptors[:-1],
            relative_path.parts[:-1],
            descriptors[1:],
            strict=True,
        ):
            opened_directory = os.fstat(child_descriptor)
            named_directory = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened_directory.st_mode)
                or not stat.S_ISDIR(named_directory.st_mode)
                or (opened_directory.st_dev, opened_directory.st_ino)
                != (named_directory.st_dev, named_directory.st_ino)
            ):
                raise ValueError("chat session directory changed while it was read")

        named_root = os.stat(resolved_root, follow_symlinks=False)
        opened_root = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(named_root.st_mode)
            or (named_root.st_dev, named_root.st_ino)
            != (opened_root.st_dev, opened_root.st_ino)
        ):
            raise ValueError("active vault changed while the chat session was read")
        return b"".join(chunks).decode("utf-8")
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


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
