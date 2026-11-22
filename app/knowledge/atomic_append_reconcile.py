"""One simple, crash-consistent in-place append for vault notes (#4659).

The primitive adds one entry to the END of an existing note through a single
``O_APPEND`` write on a descriptor it holds, followed by a single sync. It never
renames, exchanges, replaces, links, truncates, deletes or re-permissions
anything, creates no stage file and keeps no state outside the note.

Entry format (plain text, no control bytes)::

    <!--ya:begin ID h=HHHHHHHH-->
    the entry text (always ends with a newline)
    <!--ya:end ID b=BBBBBBBB-->

``ID`` is the caller's operation id (32 lowercase hex). ``h`` is 8 hex of the
SHA-256 of the caller's text; ``b`` is 8 hex of the SHA-256 of the body as
written. A marker line only counts when the whole line has exactly this shape
(trailing spaces and a CR are allowed); anything else is plain text. The first
closed entry for an ``ID`` is the entry for that operation; later closed entries
with the same ``ID`` are plain text. A new ``begin`` while an entry is open turns
the earlier one into plain text. An entry still open at end of file is a cut-off
tail, and so is an unterminated last line that starts like a ``begin`` marker.

The owner may edit anything in the note. Editing, reflowing or deleting an entry
or a marker line never blocks a later append. See
``docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Vault-bound atomic append/reconcile``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import hashlib
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge.write_ops import KNOWLEDGE_WRITE_ACTION, _candidate_relative_parts

if TYPE_CHECKING:
    from app.write_guard import WriteGuard

MAX_NOTE_BYTES = 16 * 1024 * 1024
DEFAULT_DEADLINE_SECONDS = 30.0
CUT_OFF_NOTICE = (
    "> [!note] An unfinished entry above was cut off by an interrupted write. "
    "It is kept as plain text."
)

AppendOutcomeName = Literal["appended", "reconciled_replay"]

_BEGIN_RE = re.compile(rb"<!--ya:begin ([0-9a-f]{32}) h=([0-9a-f]{8})-->[ ]*\r?")
_END_RE = re.compile(rb"<!--ya:end ([0-9a-f]{32}) b=([0-9a-f]{8})-->[ ]*\r?")
_OPERATION_ID_RE = re.compile(r"[0-9a-f]{32}")
_TAIL_LINE_START = b"<!--ya"

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_NOTE_FLAGS = (
    os.O_RDWR
    | os.O_APPEND
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)

# Linux ``statfs.f_type`` values of storage the primitive does not support.
_UNSUPPORTED_LINUX_FS = {
    0x6969: "nfs",
    0x517B: "smb",
    0xFE534D42: "smb2",
    0xFF534D42: "cifs",
    0x65735546: "fuse",
    0x01021994: "tmpfs",
    0x858458F6: "ramfs",
    0x00C36400: "ceph",
    0x5346414F: "afs",
    0x01021997: "9p",
    0x73757245: "coda",
}
_UNSUPPORTED_DARWIN_FS = {"nfs", "smbfs", "afpfs", "webdav", "ftp", "tmpfs", "autofs"}


class AtomicAppendCollision(KnowledgeWriteConflict):
    """The operation id was already used with different entry text."""


@dataclass(frozen=True)
class AtomicAppendResult:
    """Outcome of one call. ``edited`` is only meaningful for a replay."""

    outcome: AppendOutcomeName
    edited: bool = False


# --- test seams (process-death injection and ordering) -------------------------

_CHECKPOINT: Callable[[str], None] | None = None


def _checkpoint(name: str) -> None:
    if _CHECKPOINT is not None:
        _CHECKPOINT(name)


def _write(fd: int, data: bytes) -> int:
    return os.write(fd, data)


def _sync_file(fd: int) -> None:
    if sys.platform == "darwin":
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    else:
        os.fsync(fd)


def _sync_directory(fd: int) -> None:
    _sync_file(fd)


# --- parsing --------------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    h: str
    edited: bool


@dataclass(frozen=True)
class _Parsed:
    entries: dict[str, _Entry]
    damaged: frozenset[str]
    tail_start: int | None


def _sha8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _body_is_damaged(body: bytes) -> bool:
    if b"\x00" in body:
        return True
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _parse(data: bytes) -> _Parsed:
    entries: dict[str, _Entry] = {}
    damaged: set[str] = set()
    open_id: str | None = None
    open_h = ""
    open_start = 0
    open_body_start = 0
    pos = 0
    last_start = 0
    last_unterminated = False
    size = len(data)
    while pos < size:
        newline = data.find(b"\n", pos)
        if newline == -1:
            last_start = pos
            last_unterminated = True
            break
        line = data[pos:newline]
        line_end = newline + 1
        begin = _BEGIN_RE.fullmatch(line)
        if begin is not None:
            open_id = begin.group(1).decode("ascii")
            open_h = begin.group(2).decode("ascii")
            open_start = pos
            open_body_start = line_end
        elif open_id is not None:
            end = _END_RE.fullmatch(line)
            if end is not None and end.group(1).decode("ascii") == open_id:
                body = data[open_body_start:pos]
                if _body_is_damaged(body):
                    damaged.add(open_id)
                elif open_id not in entries:
                    entries[open_id] = _Entry(
                        h=open_h,
                        edited=_sha8(body) != end.group(2).decode("ascii"),
                    )
                open_id = None
        pos = line_end
    tail_start: int | None = None
    if open_id is not None:
        tail_start = open_start
    elif last_unterminated and data[last_start:].startswith(_TAIL_LINE_START):
        tail_start = last_start
    return _Parsed(entries=entries, damaged=frozenset(damaged), tail_start=tail_start)


# --- entry construction ---------------------------------------------------------


def _validate_text(text: str) -> bytes:
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("entry text must be valid UTF-8") from exc
    if b"\x00" in raw:
        raise ValueError("entry text must not contain NUL")
    for line in raw.split(b"\n"):
        if _BEGIN_RE.fullmatch(line) or _END_RE.fullmatch(line):
            raise ValueError("entry text must not contain a marker line")
    return raw


def _entry_bytes(operation_id: str, raw_text: bytes) -> bytes:
    body = raw_text if raw_text.endswith(b"\n") else raw_text + b"\n"
    return (
        f"<!--ya:begin {operation_id} h={_sha8(raw_text)}-->\n".encode("ascii")
        + body
        + f"<!--ya:end {operation_id} b={_sha8(body)}-->\n".encode("ascii")
    )


# --- filesystem helpers ---------------------------------------------------------


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _filesystem_type(fd: int) -> str:
    """Return a short filesystem label; raise when it cannot be determined."""

    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    buffer = ctypes.create_string_buffer(4096)
    if sys.platform == "darwin":
        fstatfs = getattr(libc, "fstatfs$INODE64", None) or libc.fstatfs
        if fstatfs(fd, buffer) != 0:
            raise OSError(ctypes.get_errno(), "fstatfs failed")
        return buffer.raw[72:88].split(b"\0", 1)[0].decode("ascii", "replace")
    if sys.platform.startswith("linux"):
        if libc.fstatfs(fd, buffer) != 0:
            raise OSError(ctypes.get_errno(), "fstatfs failed")
        f_type = int.from_bytes(buffer.raw[0:8], sys.byteorder) & 0xFFFFFFFF
        return _UNSUPPORTED_LINUX_FS.get(f_type, f"0x{f_type:x}")
    raise OSError(errno.ENOSYS, "unsupported platform")


def _require_supported_storage(fd: int, note_rel_path: str) -> None:
    try:
        label = _filesystem_type(fd)
    except OSError as exc:
        raise KnowledgeCapabilityError(
            f"atomic append cannot identify the storage of {note_rel_path}"
        ) from exc
    unsupported = (
        label in _UNSUPPORTED_LINUX_FS.values()
        or label in _UNSUPPORTED_DARWIN_FS
        or "fuse" in label.lower()
    )
    if unsupported:
        raise KnowledgeCapabilityError(
            f"atomic append does not support {label} storage for {note_rel_path}"
        )


def _has_file_capability(fd: int) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        os.getxattr(fd, "security.capability")
    except OSError as exc:
        if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return False
        raise
    return True


def _walk_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    """Open the parent directory of the note beneath ``root_fd`` without following links."""

    current = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = child
    except BaseException:
        os.close(current)
        raise
    return current


def _require_anchored(
    root_fd: int,
    lexical_root: str,
    parts: tuple[str, ...],
    parent_fd: int,
    note_rel_path: str,
) -> None:
    try:
        named_root = os.stat(lexical_root)
        if not _same_identity(named_root, os.fstat(root_fd)):
            raise KnowledgeWriteConflict(f"vault root changed for {note_rel_path}")
        again = _walk_parent(root_fd, parts)
    except OSError as exc:
        raise KnowledgeWriteConflict(f"vault path changed for {note_rel_path}") from exc
    try:
        if not _same_identity(os.fstat(again), os.fstat(parent_fd)):
            raise KnowledgeWriteConflict(f"vault parent changed for {note_rel_path}")
    finally:
        os.close(again)


def _require_name_maps_to_file(
    parent_fd: int, name: str, opened: os.stat_result, note_rel_path: str
) -> None:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise KnowledgeWriteConflict(f"note name changed for {note_rel_path}") from exc
    if (
        not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or not _same_identity(named, opened)
    ):
        raise KnowledgeWriteConflict(f"note name changed for {note_rel_path}")


def _read_all(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(size - offset, 1 << 20), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _lock_note(fd: int, deadline: float, note_rel_path: str) -> None:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise KnowledgeWriteConflict(
                    f"atomic append deadline passed waiting for {note_rel_path}"
                ) from None
            time.sleep(0.005)


# --- the primitive --------------------------------------------------------------


def atomic_append_reconcile_relative(
    note_rel_path: str,
    operation_id: str,
    text: str,
    *,
    vault_root: Path | str,
    create: bool = False,
    deadline: float | None = None,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
) -> AtomicAppendResult:
    """Append one entry to the end of a vault note exactly once.

    ``deadline`` is an absolute ``time.monotonic()`` value; by default the call
    waits at most ``DEFAULT_DEADLINE_SECONDS``. Returns ``appended`` or
    ``reconciled_replay``; raises ``AtomicAppendCollision`` when ``operation_id``
    was used with different text, and ``KnowledgeCapabilityError`` /
    ``KnowledgeWriteConflict`` when the target is refused or the entry cannot be
    shown to be written.
    """

    parts = _candidate_relative_parts(note_rel_path)
    if not _OPERATION_ID_RE.fullmatch(operation_id):
        raise ValueError("operation id must be 32 lowercase hex characters")
    raw_text = _validate_text(text)
    entry = _entry_bytes(operation_id, raw_text)
    expected_h = _sha8(raw_text)
    if deadline is None:
        deadline = time.monotonic() + DEFAULT_DEADLINE_SECONDS
    lexical_root = os.path.abspath(os.path.expanduser(os.fspath(vault_root)))
    name = parts[-1]

    def preflight() -> None:
        # Guard-at-seam: same checks as the sibling vault write seams, repeated
        # immediately before the one write.
        from app.instance.context_bound_write import require_effect_locator
        from app.write_guard import DEFAULT_WRITE_GUARD

        (write_guard or DEFAULT_WRITE_GUARD).assert_writes_allowed(action)
        require_effect_locator(Path(lexical_root), note_rel_path)
        if time.monotonic() >= deadline:
            raise KnowledgeWriteConflict(f"atomic append deadline passed for {note_rel_path}")

    preflight()
    root_fd = os.open(lexical_root, _DIRECTORY_FLAGS & ~getattr(os, "O_NOFOLLOW", 0))
    parent_fd: int | None = None
    note_fd: int | None = None
    try:
        try:
            parent_fd = _walk_parent(root_fd, parts)
        except OSError as exc:
            raise KnowledgeCapabilityError(
                f"atomic append parent of {note_rel_path} must be an existing in-vault directory"
            ) from exc
        _require_supported_storage(parent_fd, note_rel_path)

        created = False
        try:
            # Never open a symlink, device or FIFO (opening could block or act
            # on something that is not a note).
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode):
                raise KnowledgeCapabilityError(
                    f"atomic append target {note_rel_path} must be a regular non-symlink file"
                )
        except FileNotFoundError:
            pass
        try:
            note_fd = os.open(name, _NOTE_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                raise KnowledgeCapabilityError(
                    f"atomic append target {note_rel_path} does not exist"
                ) from None
            try:
                note_fd = os.open(
                    name, _NOTE_FLAGS | os.O_CREAT | os.O_EXCL, 0o666, dir_fd=parent_fd
                )
                created = True
            except FileExistsError:
                note_fd = os.open(name, _NOTE_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise KnowledgeCapabilityError(
                f"atomic append target {note_rel_path} must be a regular non-symlink file"
            ) from exc

        _lock_note(note_fd, deadline, note_rel_path)
        opened = os.fstat(note_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise KnowledgeCapabilityError(f"atomic append target {note_rel_path} must be a regular file")
        if opened.st_nlink != 1:
            raise KnowledgeCapabilityError(f"atomic append refuses a multiply-linked target {note_rel_path}")
        if opened.st_mode & (stat.S_ISUID | stat.S_ISGID) or _has_file_capability(note_fd):
            raise KnowledgeCapabilityError(
                f"atomic append refuses a note with special permission bits: {note_rel_path}"
            )
        if opened.st_size > MAX_NOTE_BYTES:
            raise KnowledgeCapabilityError(f"atomic append refuses a note over 16 MiB: {note_rel_path}")
        _require_supported_storage(note_fd, note_rel_path)
        _require_anchored(root_fd, lexical_root, parts, parent_fd, note_rel_path)
        _require_name_maps_to_file(parent_fd, name, opened, note_rel_path)

        if created:
            try:
                _sync_file(note_fd)
                _sync_directory(parent_fd)
            except OSError as exc:
                raise KnowledgeWriteConflict(
                    f"creating {note_rel_path} could not be made durable"
                ) from exc

        data = _read_all(note_fd, opened.st_size)
        parsed = _parse(data)

        existing = parsed.entries.get(operation_id)
        if existing is not None:
            if existing.h != expected_h:
                raise AtomicAppendCollision(
                    f"operation id already used with different text in {note_rel_path}"
                )
            return AtomicAppendResult("reconciled_replay", edited=existing.edited)

        payload = _plan_write(data, parsed, operation_id, entry)
        if len(data) + len(payload) > MAX_NOTE_BYTES:
            raise KnowledgeCapabilityError(f"atomic append would take {note_rel_path} over 16 MiB")

        _checkpoint("before_final_checks")
        preflight()
        _require_anchored(root_fd, lexical_root, parts, parent_fd, note_rel_path)
        _require_name_maps_to_file(parent_fd, name, os.fstat(note_fd), note_rel_path)

        _checkpoint("before_write")
        written = _write(note_fd, payload)
        _checkpoint("after_write")
        if written != len(payload):
            raise KnowledgeWriteConflict(
                f"atomic append to {note_rel_path} was cut short; retry the same operation"
            )
        try:
            _sync_file(note_fd)
        except OSError as exc:
            raise KnowledgeWriteConflict(
                f"atomic append to {note_rel_path} could not be made durable"
            ) from exc
        _checkpoint("after_sync")
        _read_back(note_fd, payload, operation_id, expected_h, note_rel_path)
        return AtomicAppendResult("appended")
    finally:
        if note_fd is not None:
            os.close(note_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def _plan_write(data: bytes, parsed: _Parsed, operation_id: str, entry: bytes) -> bytes:
    """Return the one byte string to append: the missing rest, or a new entry."""

    if parsed.tail_start is not None:
        tail = data[parsed.tail_start :]
        if len(tail) < len(entry) and entry.startswith(tail):
            return entry[len(tail) :]
    # A note that does not end in a newline gets one first, so the entry starts on
    # its own line. That newline can itself finish an entry whose only missing
    # byte was its last one; such an entry is complete, not cut off.
    payload = b""
    tail_open = parsed.tail_start is not None
    damaged = parsed.damaged
    if data and not data.endswith(b"\n"):
        payload = b"\n"
        after = _parse(data + payload)
        tail_open = tail_open and len(after.entries) == len(parsed.entries)
        damaged = damaged | after.damaged
    if tail_open or operation_id in damaged:
        payload += CUT_OFF_NOTICE.encode("utf-8") + b"\n"
    return payload + entry


def _read_back(
    fd: int, payload: bytes, operation_id: str, expected_h: str, note_rel_path: str
) -> None:
    end = os.lseek(fd, 0, os.SEEK_CUR)
    still_named = os.fstat(fd)
    if still_named.st_nlink < 1:
        raise KnowledgeWriteConflict(
            f"{note_rel_path} lost its last name during the append; nothing was written to a note"
        )
    start = end - len(payload)
    if start < 0 or os.pread(fd, len(payload), start) != payload:
        raise KnowledgeWriteConflict(
            f"atomic append to {note_rel_path} did not read back; retry the same operation"
        )
    entry = _parse(_read_all(fd, still_named.st_size)).entries.get(operation_id)
    if entry is None or entry.h != expected_h:
        raise KnowledgeWriteConflict(
            f"atomic append to {note_rel_path} did not read back; retry the same operation"
        )
