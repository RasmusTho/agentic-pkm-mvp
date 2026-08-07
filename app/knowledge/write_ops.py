from __future__ import annotations

import errno
import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import TYPE_CHECKING, Callable, Iterator, Literal
import uuid

from app.knowledge.adapters import (
    _atomic_exchange_at,
    _atomic_rename_noreplace_at,
    _open_conflict_directory,
    _read_stable_descriptor,
    _same_file_identity,
)
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings
from app.knowledge.service import resolve_knowledge_port

if TYPE_CHECKING:
    from app.write_guard import WriteGuard

# Default action asserted at both knowledge write ports (#2910 for
# ``write_note_from_absolute``, extended to ``write_note_relative`` by #2953,
# formal-model.md §3 gap 1 / P-1). This is the shared root-cause seam: ~20
# production call sites reach the vault through these two ports with no
# WriteGuard at the port itself -- some already assert caller-side with their
# own distinct action string (defense-in-depth, e.g. #2808/#2809), but several
# (promotion queue, vault layout, filesystem vault adapter, alpha human flows,
# and -- for the relative-path port -- ``app/mcp/vault_tools.py``) reached the
# vault completely unguarded. Asserting here with a generic default action
# closes every one of those gaps in a single change, and is safe/idempotent
# for callers that already asserted their own action.
KNOWLEDGE_WRITE_ACTION = "knowledge.write_note"
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_CANDIDATE_STAGE_OPEN_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
CandidateCreateResult = Literal["written", "already_exists"]
AtomicAppendTransform = Callable[[bytes | None, bytes], tuple[bytes, bytes]]
_ATOMIC_APPEND_STAGE_RE = re.compile(
    r"^\.atomic-append-(?P<transaction>[0-9a-f]{32})-"
    r"(?P<digest>[0-9a-f]{64})-(?P<source>absent|[0-9]+-[0-9]+)\.stage$"
)
_ATOMIC_APPEND_RECOVERY_TEMP_RE = re.compile(
    r"^\.atomic-append-recovery-[0-9a-f]{32}-[a-z]+-[0-9a-f]{32}\.tmp$"
)


@dataclass(frozen=True)
class _AtomicAppendAuthority:
    """One internally opened root/locator authority shared by lock and write."""

    root_fd: int
    root_path: Path
    lexical_root_path: Path
    root_stat: os.stat_result
    note_rel_path: str
    lock_key: str
    canonical_path_lock_key: str
    lexical_path_lock_key: str
    path_lock_keys: tuple[str, ...]
    host_state_fd: int | None = None
    host_state_stat: os.stat_result | None = None
    host_witness_root_path: Path | None = None
    host_witness_root_fd: int | None = None
    host_witness_root_stat: os.stat_result | None = None
    host_witness_fds: tuple[tuple[str, int], ...] = ()

    @property
    def host_state_keys(self) -> tuple[str, ...]:
        # Durable state follows the opened resource and its filesystem-reported
        # canonical path. Caller spellings remain live lock fences only: adding
        # a symlink or case alias must not change the persisted record set.
        return tuple(dict.fromkeys((self.lock_key, self.canonical_path_lock_key)))

    @property
    def route_key(self) -> str:
        return f"route:{self.lexical_path_lock_key}"

    @property
    def coordination_keys(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (self.lock_key, *self.path_lock_keys, self.route_key)
            )
        )

    def assert_live(self) -> None:
        try:
            current = os.stat(self.root_path, follow_symlinks=False)
            lexical_current = os.stat(self.lexical_root_path)
            opened = os.fstat(self.root_fd)
        except OSError as exc:
            raise KnowledgeWriteConflict(
                f"atomic append authority mapping changed for {self.note_rel_path}"
            ) from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or not _same_file_identity(current, self.root_stat)
            or not _same_file_identity(lexical_current, self.root_stat)
            or not _same_file_identity(opened, self.root_stat)
        ):
            raise KnowledgeWriteConflict(
                f"atomic append authority mapping changed for {self.note_rel_path}"
            )

    def assert_host_state_live(self) -> None:
        if self.host_state_fd is None or self.host_state_stat is None:
            raise AssertionError("atomic append host state authority is not bound")
        try:
            current = os.stat(
                _atomic_append_host_fence_root(self),
                follow_symlinks=False,
            )
            opened = os.fstat(self.host_state_fd)
        except OSError as exc:
            raise KnowledgeWriteConflict(
                f"atomic append host state authority changed for {self.note_rel_path}"
            ) from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or not _same_file_identity(current, self.host_state_stat)
            or not _same_file_identity(opened, self.host_state_stat)
        ):
            raise KnowledgeWriteConflict(
                f"atomic append host state authority changed for {self.note_rel_path}"
            )

    def assert_host_witness_live(self) -> None:
        if (
            self.host_witness_root_path is None
            or self.host_witness_root_fd is None
            or self.host_witness_root_stat is None
            or not self.host_witness_fds
        ):
            raise AssertionError("atomic append host witness authority is not bound")
        try:
            current_root = os.stat(
                self.host_witness_root_path,
                follow_symlinks=False,
            )
            opened_root = os.fstat(self.host_witness_root_fd)
            if (
                not stat.S_ISDIR(current_root.st_mode)
                or not _same_file_identity(current_root, self.host_witness_root_stat)
                or not _same_file_identity(opened_root, self.host_witness_root_stat)
            ):
                raise KnowledgeWriteConflict(
                    f"atomic append host witness authority changed for "
                    f"{self.note_rel_path}"
                )
            for path_lock_key, witness_fd in self.host_witness_fds:
                name = f"{hashlib.sha256(path_lock_key.encode('utf-8')).hexdigest()}.lock"
                named = os.stat(
                    name,
                    dir_fd=self.host_witness_root_fd,
                    follow_symlinks=False,
                )
                opened = os.fstat(witness_fd)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or named.st_nlink != 1
                    or not _same_file_identity(named, opened)
                ):
                    raise KnowledgeWriteConflict(
                        f"atomic append host witness authority changed for "
                        f"{self.note_rel_path}"
                    )
        except KnowledgeWriteConflict:
            raise
        except OSError as exc:
            raise KnowledgeWriteConflict(
                f"atomic append host witness authority changed for {self.note_rel_path}"
            ) from exc


def _opened_directory_path(fd: int, fallback: Path) -> Path:
    """Return the filesystem-reported path for an already-open directory."""

    raw: bytes | str
    try:
        if sys.platform == "darwin":
            # F_GETPATH reports the filesystem's preserved spelling rather
            # than the spelling used by the caller to reach the directory.
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0]
        elif sys.platform.startswith("linux"):
            raw = os.readlink(f"/proc/self/fd/{fd}")
        else:
            return fallback
    except OSError:
        return fallback
    candidate = Path(os.fsdecode(raw))
    return candidate if candidate.is_absolute() else fallback


def _filesystem_reported_lexical_path(path: Path) -> Path:
    """Preserve a route while using the filesystem's entry spelling."""

    flags = getattr(os, "O_CLOEXEC", 0)
    if sys.platform == "darwin":
        flags |= getattr(os, "O_SYMLINK", 0)
    elif sys.platform.startswith("linux") and hasattr(os, "O_PATH"):
        flags |= os.O_PATH | getattr(os, "O_NOFOLLOW", 0)
    else:
        return path
    try:
        route_fd = os.open(path, flags)
    except OSError:
        return path
    try:
        return _opened_directory_path(route_fd, path)
    finally:
        os.close(route_fd)


@contextmanager
def _open_atomic_append_authority(
    vault_root: Path | str,
    note_rel_path: str,
) -> Iterator[_AtomicAppendAuthority]:
    """Open the exact root whose identity selects the per-resource lock."""

    _candidate_relative_parts(note_rel_path)
    lexical_root_path = Path(
        os.path.abspath(os.path.expanduser(os.fspath(vault_root)))
    )
    requested_root_path = lexical_root_path.resolve()
    root_fd = os.open(requested_root_path, _DIRECTORY_OPEN_FLAGS)
    try:
        root_stat = os.fstat(root_fd)
        root_path = _opened_directory_path(root_fd, requested_root_path)
        lexical_route_path = _filesystem_reported_lexical_path(lexical_root_path)
        canonical_path_lock_key = f"{os.fspath(root_path)}:{note_rel_path}"
        lexical_path_lock_key = f"{os.fspath(lexical_route_path)}:{note_rel_path}"
        path_lock_keys = tuple(
            dict.fromkeys((canonical_path_lock_key, lexical_path_lock_key))
        )
        authority = _AtomicAppendAuthority(
            root_fd=root_fd,
            root_path=root_path,
            lexical_root_path=lexical_root_path,
            root_stat=root_stat,
            note_rel_path=note_rel_path,
            lock_key=(
                f"{root_stat.st_dev}:{root_stat.st_ino}:{note_rel_path}"
            ),
            canonical_path_lock_key=canonical_path_lock_key,
            lexical_path_lock_key=lexical_path_lock_key,
            path_lock_keys=path_lock_keys,
        )
        authority.assert_live()
        yield authority
    finally:
        os.close(root_fd)


@dataclass(frozen=True)
class _AccessMetadata:
    mode: int
    uid: int
    gid: int
    xattrs: tuple[tuple[str, bytes], ...]
    acl: bytes | None


@dataclass(frozen=True)
class _RecoveryEntry:
    name: str
    identity: os.stat_result
    digest: str
    metadata: _AccessMetadata
    fd: int


def _access_metadata_host_payload(metadata: _AccessMetadata) -> dict[str, object]:
    """Encode exact access metadata into a stable JSON-compatible value."""

    return {
        "mode": metadata.mode,
        "uid": metadata.uid,
        "gid": metadata.gid,
        "xattrs": [[name, value.hex()] for name, value in metadata.xattrs],
        "acl": metadata.acl.hex() if metadata.acl is not None else None,
    }


def _split_frontmatter_body_bytes(raw: bytes) -> tuple[bytes, bytes]:
    """Split a Markdown note without normalizing any body byte."""

    if not (raw.startswith(b"---\n") or raw.startswith(b"---\r\n")):
        raise ValueError("atomic append target is missing YAML frontmatter")
    offset = 0
    for index, line in enumerate(raw.splitlines(keepends=True)):
        content = line.rstrip(b"\r\n")
        if index > 0 and content == b"---":
            closing_end = offset + len(content)
            return raw[:closing_end], raw[closing_end:]
        offset += len(line)
    raise ValueError("atomic append target has unterminated YAML frontmatter")


def _read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "atomic append stage write made no progress")
        view = view[written:]


def _darwin_acl_text(fd: int) -> bytes | None:
    if sys.platform != "darwin":
        return None

    libc = ctypes.CDLL(None, use_errno=True)
    acl_get_fd = libc.acl_get_fd_np
    acl_get_fd.argtypes = [ctypes.c_int, ctypes.c_int]
    acl_get_fd.restype = ctypes.c_void_p
    acl_to_text = libc.acl_to_text
    acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
    acl_to_text.restype = ctypes.c_void_p
    acl_free = libc.acl_free
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int

    ctypes.set_errno(0)
    acl = acl_get_fd(fd, 0x00000100)  # ACL_TYPE_EXTENDED
    if not acl:
        error = ctypes.get_errno()
        if error == errno.ENOENT:
            return None
        raise OSError(error, os.strerror(error))
    rendered: int | None = None
    try:
        length = ctypes.c_ssize_t()
        rendered = acl_to_text(acl, ctypes.byref(length))
        if not rendered:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return ctypes.string_at(rendered, length.value)
    finally:
        if rendered:
            acl_free(rendered)
        acl_free(acl)


def _fd_xattrs(fd: int) -> tuple[tuple[str, bytes], ...]:
    if hasattr(os, "listxattr") and hasattr(os, "getxattr"):
        listxattr = getattr(os, "listxattr")
        getxattr = getattr(os, "getxattr")
        return tuple(
            sorted(
                (name, getxattr(fd, name))
                for name in listxattr(fd)
            )
        )
    if sys.platform != "darwin":
        raise KnowledgeCapabilityError(
            "platform cannot prove atomic append ACL/xattr preservation"
        )

    libc = ctypes.CDLL(None, use_errno=True)
    flistxattr = libc.flistxattr
    flistxattr.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    flistxattr.restype = ctypes.c_ssize_t
    fgetxattr = libc.fgetxattr
    fgetxattr.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    fgetxattr.restype = ctypes.c_ssize_t

    size = flistxattr(fd, None, 0, 0)
    if size < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if size == 0:
        return ()
    names_buffer = ctypes.create_string_buffer(size)
    actual = flistxattr(fd, names_buffer, size, 0)
    if actual < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    names = [name for name in names_buffer.raw[:actual].split(b"\0") if name]
    result: list[tuple[str, bytes]] = []
    for raw_name in names:
        value_size = fgetxattr(fd, raw_name, None, 0, 0, 0)
        if value_size < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        value_buffer = ctypes.create_string_buffer(value_size)
        value_actual = fgetxattr(fd, raw_name, value_buffer, value_size, 0, 0)
        if value_actual < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        result.append(
            (raw_name.decode("utf-8", errors="surrogateescape"), value_buffer.raw[:value_actual])
        )
    return tuple(sorted(result))


def _access_metadata(fd: int) -> _AccessMetadata:
    observed = os.fstat(fd)
    return _AccessMetadata(
        mode=stat.S_IMODE(observed.st_mode),
        uid=observed.st_uid,
        gid=observed.st_gid,
        xattrs=_fd_xattrs(fd),
        acl=_darwin_acl_text(fd),
    )


def _copy_access_metadata(
    source_fd: int,
    staged_fd: int,
    *,
    allow_unlinked_source: bool = False,
) -> None:
    """Clone and prove access metadata after staged payload I/O is complete."""

    source = os.fstat(source_fd)
    if source.st_nlink != 1 and not (
        allow_unlinked_source and source.st_nlink == 0
    ):
        raise KnowledgeCapabilityError(
            "atomic append refuses a multiply-linked target"
        )

    if sys.platform == "darwin":
        # COPYFILE_METADATA = ACL | STAT | XATTR. Data is deliberately omitted
        # because the staged transaction writes its own complete payload.
        fcopyfile = ctypes.CDLL(None, use_errno=True).fcopyfile
        fcopyfile.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        fcopyfile.restype = ctypes.c_int
        if fcopyfile(source_fd, staged_fd, None, 0x00000007) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    else:
        staged = os.fstat(staged_fd)
        if (staged.st_uid, staged.st_gid) != (source.st_uid, source.st_gid):
            os.fchown(staged_fd, source.st_uid, source.st_gid)
        required_xattr_apis = ("listxattr", "getxattr", "setxattr")
        if not all(hasattr(os, name) for name in required_xattr_apis):
            raise KnowledgeCapabilityError(
                "platform cannot prove atomic append ACL/xattr preservation"
            )
        for attribute in os.listxattr(source_fd):
            os.setxattr(staged_fd, attribute, os.getxattr(source_fd, attribute))
        # chown and payload writes can clear setuid/setgid bits. Mode is the
        # final metadata mutation on non-macOS platforms for that reason.
        os.fchmod(staged_fd, stat.S_IMODE(source.st_mode))

    if _access_metadata(staged_fd) != _access_metadata(source_fd):
        raise KnowledgeCapabilityError(
            "atomic append access metadata could not be preserved exactly"
        )


def _candidate_relative_parts(note_rel_path: str) -> tuple[str, ...]:
    if not note_rel_path or "\x00" in note_rel_path or "\\" in note_rel_path:
        raise ValueError("candidate note path must be a portable vault-relative POSIX path")
    path = PurePosixPath(note_rel_path)
    if path.is_absolute() or path.as_posix() != note_rel_path:
        raise ValueError("candidate note path must be a normalized vault-relative POSIX path")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("candidate note path must stay inside the vault")
    return parts


def _require_regular_candidate_target(
    parent_fd: int,
    target_name: str,
) -> None:
    target_stat = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(target_stat.st_mode):
        raise OSError(
            errno.EINVAL,
            "candidate target exists but is not a regular file",
            target_name,
        )


def candidate_note_exists_durable(
    note_rel_path: str,
    *,
    vault_root: Path | str,
) -> bool:
    """Durably observe a regular candidate target without mutating the vault."""

    parts = _candidate_relative_parts(note_rel_path)
    resolved_root = Path(vault_root).expanduser().resolve()
    current_dir_fd: int | None = None
    try:
        current_dir_fd = os.open(resolved_root, _DIRECTORY_OPEN_FLAGS)
        for component in parts[:-1]:
            try:
                child_fd = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=current_dir_fd,
                )
            except FileNotFoundError:
                return False
            superseded_fd = current_dir_fd
            current_dir_fd = child_fd
            os.close(superseded_fd)

        try:
            _require_regular_candidate_target(current_dir_fd, parts[-1])
        except FileNotFoundError:
            return False
        os.fsync(current_dir_fd)
        return True
    finally:
        if current_dir_fd is not None:
            owned_fd = current_dir_fd
            current_dir_fd = None
            os.close(owned_fd)


def create_candidate_note_once(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str,
    write_guard: "WriteGuard | None" = None,
) -> CandidateCreateResult:
    """Create one candidate atomically, preserving any existing target.

    This is deliberately candidate-specific. It owns only invocation-local
    parent preparation and one hidden stage; it does not change generic
    ``KnowledgePort.write_note`` semantics or coordinate other writers.
    """

    from app.write_guard import DEFAULT_WRITE_GUARD

    parts = _candidate_relative_parts(note_rel_path)
    resolved_root = Path(vault_root).expanduser().resolve()
    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    payload = content.encode("utf-8")

    current_dir_fd: int | None = None
    stage_fd: int | None = None
    stage_name: str | None = None
    stage_owned = False
    stage_unlink_attempted = False
    cleanup_error: BaseException | None = None

    def record_cleanup_error(exc: BaseException) -> None:
        nonlocal cleanup_error
        if cleanup_error is None:
            cleanup_error = exc

    try:
        current_dir_fd = os.open(resolved_root, _DIRECTORY_OPEN_FLAGS)
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o777, dir_fd=current_dir_fd)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
            os.fsync(current_dir_fd)
            child_fd = os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current_dir_fd,
            )
            superseded_fd = current_dir_fd
            current_dir_fd = child_fd
            os.close(superseded_fd)

        stage_name = f".candidate-stage-{uuid.uuid4().hex}"
        stage_fd = os.open(
            stage_name,
            _CANDIDATE_STAGE_OPEN_FLAGS,
            0o600,
            dir_fd=current_dir_fd,
        )
        stage_owned = True
        offset = 0
        while offset < len(payload):
            written = os.write(stage_fd, payload[offset:])
            if written <= 0:
                raise OSError(
                    errno.EIO,
                    "candidate stage write made no progress",
                    stage_name,
                )
            offset += written
        os.fsync(stage_fd)
        owned_stage_fd = stage_fd
        stage_fd = None
        os.close(owned_stage_fd)

        try:
            _atomic_rename_noreplace_at(
                current_dir_fd,
                stage_name,
                current_dir_fd,
                parts[-1],
            )
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            stage_unlink_attempted = True
            os.unlink(stage_name, dir_fd=current_dir_fd)
            stage_owned = False
            os.fsync(current_dir_fd)
            _require_regular_candidate_target(current_dir_fd, parts[-1])
            return "already_exists"

        stage_owned = False
        os.fsync(current_dir_fd)
        return "written"
    finally:
        if stage_fd is not None:
            owned_stage_fd = stage_fd
            stage_fd = None
            try:
                os.close(owned_stage_fd)
            except BaseException as exc:  # noqa: BLE001 - preserve fail-closed cleanup
                record_cleanup_error(exc)

        if (
            stage_owned
            and not stage_unlink_attempted
            and stage_name is not None
            and current_dir_fd is not None
        ):
            stage_unlink_attempted = True
            try:
                os.unlink(stage_name, dir_fd=current_dir_fd)
            except BaseException as exc:  # noqa: BLE001 - exact owned-stage cleanup
                record_cleanup_error(exc)
            else:
                stage_owned = False
                try:
                    os.fsync(current_dir_fd)
                except BaseException as exc:  # noqa: BLE001 - cleanup durability is required
                    record_cleanup_error(exc)

        if current_dir_fd is not None:
            owned_dir_fd = current_dir_fd
            current_dir_fd = None
            try:
                os.close(owned_dir_fd)
            except BaseException as exc:  # noqa: BLE001 - every owner gets one close attempt
                record_cleanup_error(exc)

        if cleanup_error is not None:
            raise cleanup_error


def default_vault_root_for_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve()
    return Path(resolved.anchor) if resolved.anchor else Path("/")


def read_note_text_with_version(path: Path | str) -> tuple[str, str]:
    """Read once, preserving text bytes while hashing the exact filesystem payload."""

    raw = Path(path).read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def _local_fs_settings() -> KnowledgeSettings:
    return KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.FS_VAULT,
        fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        allow_fallback=False,
        strict_startup=False,
    )


def _require_canonical_write(
    receipt: WriteReceipt,
    *,
    accept_staged_conflict: bool,
) -> WriteReceipt:
    if receipt.outcome == "conflict_staged" and not accept_staged_conflict:
        artifact = receipt.conflict_artifact or "an unknown conflict artifact"
        raise KnowledgeWriteConflict(
            f"rewritten note conflict staged at {artifact}; canonical note unchanged",
            receipt=receipt,
        )
    return receipt


def write_note_from_absolute(
    path: Path | str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
    expected_version: str | None = None,
    writer_identity: str | None = None,
    accept_staged_conflict: bool = False,
) -> WriteReceipt:
    # Guard-at-seam (#2910): assert WriteGuard inside the port itself, before
    # any path resolution or filesystem mutation, so a blocked write is
    # atomic (zero bytes touched) regardless of which caller reached this
    # seam. ``action`` defaults to the generic port action but callers that
    # need the #2877 named bootstrap escape (pre-vault-selection provisioning
    # such as the yggdrasil-init scaffolder) pass their own escape action
    # string through explicitly -- the escape lives in the guard's allow-list
    # (``DEFAULT_BOOTSTRAP_ACTIONS`` in app/write_guard.py), never in an
    # unconditional skip here. A denying guard still blocks unconditionally.
    #
    # Imported lazily (not at module level): app.write_guard -> health_contract
    # -> events.outbox -> outbox.events -> events.schema -> settings.runtime ->
    # settings.compiler -> settings.writeback -> app.knowledge.write_ops closes
    # a circular import back to this module (the same cycle #2809 documented
    # for app/settings/writeback.py; this port is the shared root cause every
    # writeback caller ultimately routes through).
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    resolved_root = Path(os.path.realpath(os.path.expanduser(os.fspath(vault_root))))
    if expected_version is None:
        resolved_path = Path(os.path.realpath(os.path.expanduser(os.fspath(path))))
        resolved_path.relative_to(resolved_root)
        locator = make_note_locator_from_absolute(resolved_path, vault_root=resolved_root)
    else:
        # Preserve the caller-authorized lexical vault-relative path. Resolving
        # the leaf here would let a symlink swap between the final caller policy
        # check and this helper silently retarget a matching content token to a
        # different note. The filesystem adapter rejects an aliased
        # expected-version locator, while its descriptor/no-follow CAS protects
        # replacements after that check.
        lexical_path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        try:
            relative_path = lexical_path.relative_to(resolved_root)
        except ValueError:
            lexical_root = Path(os.path.abspath(os.path.expanduser(os.fspath(vault_root))))
            relative_path = lexical_path.relative_to(lexical_root)
        locator = make_note_locator(relative_path.as_posix())
    # Absolute path writes target the local filesystem boundary directly.
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    kwargs: dict[str, str] = {}
    if expected_version is not None:
        kwargs["expected_version"] = expected_version
    if writer_identity is not None:
        kwargs["writer_identity"] = writer_identity
    receipt = port.write_note(locator, content, **kwargs)
    return _require_canonical_write(
        receipt,
        accept_staged_conflict=accept_staged_conflict,
    )


def write_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
    expected_version: str | None = None,
    writer_identity: str | None = None,
    accept_staged_conflict: bool = False,
) -> WriteReceipt:
    # Guard-at-seam (#2953, extending #2910): assert WriteGuard inside this
    # port too, before any path resolution or filesystem mutation, mirroring
    # ``write_note_from_absolute`` exactly. Several production callers already
    # assert caller-side with their own distinct action string (defense-in-
    # depth, e.g. materialize_moment/materialize_promoted_memory/
    # write_candidate_note) -- double-assert is harmless and stays valid. But
    # at least one production caller (``app/mcp/vault_tools.py``) reached this
    # relative-path port completely unguarded; asserting here with a generic
    # default action closes that gap the same way #2910 closed it for the
    # absolute-path port. ``action`` defaults to the generic port action but
    # callers that need the #2877 named bootstrap escape pass their own escape
    # action string through explicitly -- the escape lives in the guard's
    # allow-list (``DEFAULT_BOOTSTRAP_ACTIONS`` in app/write_guard.py), never
    # in an unconditional skip here. A denying guard still blocks
    # unconditionally.
    #
    # Imported lazily for the same circular-import reason documented on
    # ``write_note_from_absolute`` above (app.write_guard -> health_contract
    # -> ... -> app.knowledge.write_ops).
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    kwargs: dict[str, str] = {}
    if expected_version is not None:
        kwargs["expected_version"] = expected_version
    if writer_identity is not None:
        kwargs["writer_identity"] = writer_identity
    receipt = port.write_note(locator, content, **kwargs)
    return _require_canonical_write(
        receipt,
        accept_staged_conflict=accept_staged_conflict,
    )


def _read_bound_file(
    fd: int,
    expected: os.stat_result,
    *,
    context: str,
) -> tuple[bytes, _AccessMetadata]:
    metadata_before = _access_metadata(fd)
    payload, observed = _read_stable_descriptor(fd)
    metadata_after = _access_metadata(fd)
    if (
        not _same_file_identity(observed, expected)
        or metadata_before != metadata_after
    ):
        raise KnowledgeWriteConflict(f"{context} changed during descriptor read")
    return payload, metadata_after


def _open_atomic_append_recovery(root_fd: int, *, create: bool = True) -> int:
    """Open the established scanner-inert root recovery convention."""

    if create:
        return _open_conflict_directory(root_fd)
    try:
        return os.open("_conflicts", _DIRECTORY_OPEN_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        raise KnowledgeWriteConflict(
            "atomic append recovery authority changed; reconciliation is required"
        ) from exc


def _atomic_append_locator_token(note_rel_path: str) -> str:
    return hashlib.sha256(note_rel_path.encode("utf-8")).hexdigest()[:24]


def _indeterminate_marker_prefix(note_rel_path: str) -> str:
    return f".steering-append-indeterminate-{_atomic_append_locator_token(note_rel_path)}-"


def _require_no_indeterminate_marker(recovery_fd: int, note_rel_path: str) -> None:
    prefix = _indeterminate_marker_prefix(note_rel_path)
    if any(name.startswith(prefix) for name in os.listdir(recovery_fd)):
        raise KnowledgeWriteConflict(
            f"atomic append authority mapping is indeterminate for {note_rel_path}; "
            "reconciliation is required before retry"
        )


def _atomic_append_host_fence_root(authority: _AtomicAppendAuthority) -> Path:
    # Lazy import avoids widening write_ops' existing settings/compiler import
    # cycle. This uses the established app-local state root rather than adding
    # another configuration surface.
    from app.instance.vault_registry import default_app_local_settings_path

    fence_root = default_app_local_settings_path().expanduser().resolve(strict=False).parent
    try:
        fence_root.relative_to(authority.root_path)
    except ValueError:
        return fence_root
    raise KnowledgeCapabilityError(
        "atomic append host fence directory must be outside the vault root"
    )


_HOST_APPEND_STATE_SCHEMA = "agentic-pkm.heimdal-atomic-append-state.v1"
_HOST_APPEND_ROUTE_SCHEMA = "agentic-pkm.heimdal-atomic-append-route.v1"
_atomic_host_state_exchange_at = _atomic_exchange_at


@dataclass(frozen=True)
class _HostStateRecord:
    identity: os.stat_result | None
    raw: bytes | None
    state: dict[str, object] | None


def _host_append_state_name(path_lock_key: str) -> str:
    token = hashlib.sha256(path_lock_key.encode("utf-8")).hexdigest()
    return f".heimdal-atomic-append-{token}.state"


def _host_append_swap_name(path_lock_key: str) -> str:
    token = hashlib.sha256(path_lock_key.encode("utf-8")).hexdigest()
    return f".heimdal-atomic-append-{token}.swap"


def _host_append_route_names(route_key: str) -> tuple[str, str]:
    token = hashlib.sha256(route_key.encode("utf-8")).hexdigest()
    return (
        f".heimdal-atomic-route-{token}.state",
        f".heimdal-atomic-route-{token}.swap",
    )


def _open_durable_host_fence_root(authority: _AtomicAppendAuthority) -> int:
    """Create every missing namespace component with a parent fsync."""

    if authority.host_state_fd is not None:
        authority.assert_host_state_live()
        return os.dup(authority.host_state_fd)

    fence_root = _atomic_append_host_fence_root(authority)
    missing: list[str] = []
    cursor = fence_root
    while True:
        try:
            current_fd = os.open(cursor, _DIRECTORY_OPEN_FLAGS)
            break
        except FileNotFoundError:
            if cursor.parent == cursor:
                raise KnowledgeCapabilityError(
                    "atomic append host fence directory has no durable parent"
                )
            missing.append(cursor.name)
            cursor = cursor.parent
        except OSError as exc:
            raise KnowledgeCapabilityError(
                "atomic append host fence namespace must contain only non-symlink directories"
            ) from exc

    try:
        for component in reversed(missing):
            try:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            os.fsync(current_fd)
            child_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            os.fsync(child_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _decode_host_append_state(
    raw: bytes,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
) -> dict[str, object]:
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeWriteConflict(
            f"atomic append host state is malformed for {authority.note_rel_path}; "
            "reconciliation is required before retry"
        ) from exc
    if (
        not isinstance(state, dict)
        or state.get("schema") != _HOST_APPEND_STATE_SCHEMA
        or state.get("path_lock_key") != path_lock_key
        or state.get("locator") != authority.note_rel_path
        or state.get("authority_keys") != sorted(authority.host_state_keys)
        or state.get("state") not in {"active", "clean", "indeterminate"}
    ):
        raise KnowledgeWriteConflict(
            f"atomic append host state is invalid for {authority.note_rel_path}; "
            "reconciliation is required before retry"
        )
    return state


def _read_host_state_record(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
    name: str,
    *,
    decode: bool = True,
) -> _HostStateRecord:
    try:
        state_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=fence_fd,
        )
    except FileNotFoundError:
        return _HostStateRecord(identity=None, raw=None, state=None)
    except OSError as exc:
        raise KnowledgeCapabilityError(
            "atomic append host state must be a regular non-symlink file"
        ) from exc
    try:
        observed = os.fstat(state_fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise KnowledgeCapabilityError(
                "atomic append host state must be one regular file"
            )
        raw, observed = _read_stable_descriptor(state_fd)
    finally:
        os.close(state_fd)
    state = (
        _decode_host_append_state(raw, authority, path_lock_key)
        if raw and decode
        else None
    )
    return _HostStateRecord(identity=observed, raw=raw, state=state)


def _read_host_append_record(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
    *,
    decode: bool = True,
) -> _HostStateRecord:
    return _read_host_state_record(
        fence_fd,
        authority,
        path_lock_key,
        _host_append_state_name(path_lock_key),
        decode=decode,
    )


def _read_host_swap_record(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
    *,
    decode: bool = True,
) -> _HostStateRecord:
    return _read_host_state_record(
        fence_fd,
        authority,
        path_lock_key,
        _host_append_swap_name(path_lock_key),
        decode=decode,
    )


def _read_host_append_state(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
) -> dict[str, object] | None:
    return _read_host_append_record(fence_fd, authority, path_lock_key).state


def _read_host_witness_state(
    witness_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
) -> dict[str, object] | None:
    duplicate = os.dup(witness_fd)
    try:
        raw = _read_all(duplicate)
    finally:
        os.close(duplicate)
    if not raw:
        return None
    return _decode_host_append_state(raw, authority, path_lock_key)


def _write_host_witness_state(
    witness_fd: int,
    payload: dict[str, object],
) -> None:
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    os.ftruncate(witness_fd, 0)
    os.lseek(witness_fd, 0, os.SEEK_SET)
    _write_all(witness_fd, raw)
    os.fsync(witness_fd)


def _open_host_state_slot(fence_fd: int, name: str) -> tuple[int, bool]:
    flags = (
        os.O_RDWR
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(
            name,
            flags | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=fence_fd,
        )
    except FileExistsError:
        fd = os.open(name, flags, dir_fd=fence_fd)
        created = False
    else:
        created = True
        try:
            os.fsync(fence_fd)
        except BaseException:
            os.close(fd)
            raise
    observed = os.fstat(fd)
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        os.close(fd)
        raise KnowledgeCapabilityError(
            "atomic append host state must be one regular file"
        )
    return fd, created


def _record_matches_snapshot(
    raw: bytes,
    observed: os.stat_result,
    created: bool,
    expected: _HostStateRecord,
) -> bool:
    if expected.identity is None:
        return created and raw == b""
    return (
        not created
        and expected.raw == raw
        and _same_file_identity(observed, expected.identity)
    )


def _write_host_append_state(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    path_lock_key: str,
    payload: dict[str, object],
    expected_state: _HostStateRecord,
    expected_swap: _HostStateRecord,
    *,
    state_name: str | None = None,
    swap_name: str | None = None,
) -> None:
    name = state_name or _host_append_state_name(path_lock_key)
    swap_name = swap_name or _host_append_swap_name(path_lock_key)
    state_fd, state_created = _open_host_state_slot(fence_fd, name)
    try:
        swap_fd, swap_created = _open_host_state_slot(fence_fd, swap_name)
    except BaseException:
        os.close(state_fd)
        raise
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        prior_raw, prior_stat = _read_stable_descriptor(state_fd)
        swap_raw, swap_stat = _read_stable_descriptor(swap_fd)
        if not _record_matches_snapshot(
            prior_raw,
            prior_stat,
            state_created,
            expected_state,
        ) or not _record_matches_snapshot(
            swap_raw,
            swap_stat,
            swap_created,
            expected_swap,
        ):
            raise KnowledgeWriteConflict(
                f"atomic append app-local state changed before transition for "
                f"{authority.note_rel_path}"
            )

        os.ftruncate(swap_fd, 0)
        os.lseek(swap_fd, 0, os.SEEK_SET)
        _write_all(swap_fd, raw)
        os.fsync(swap_fd)
        _atomic_host_state_exchange_at(fence_fd, name, fence_fd, swap_name)
        os.fsync(fence_fd)

        named_state = os.stat(name, dir_fd=fence_fd, follow_symlinks=False)
        named_swap = os.stat(swap_name, dir_fd=fence_fd, follow_symlinks=False)
        displaced_raw, displaced_stat = _read_stable_descriptor(state_fd)
        installed_raw, installed_stat = _read_stable_descriptor(swap_fd)
        if (
            not _same_file_identity(named_state, installed_stat)
            or not _same_file_identity(named_swap, displaced_stat)
            or displaced_raw != prior_raw
            or installed_raw != raw
        ):
            raise KnowledgeWriteConflict(
                f"atomic append app-local state changed during transition for "
                f"{authority.note_rel_path}"
            )

        os.ftruncate(state_fd, 0)
        os.fsync(state_fd)
        os.fsync(fence_fd)
        final_state = os.stat(name, dir_fd=fence_fd, follow_symlinks=False)
        final_swap = os.stat(swap_name, dir_fd=fence_fd, follow_symlinks=False)
        final_raw, final_stat = _read_stable_descriptor(swap_fd)
        cleared_raw, cleared_stat = _read_stable_descriptor(state_fd)
        if (
            not _same_file_identity(final_state, final_stat)
            or not _same_file_identity(final_swap, cleared_stat)
            or final_raw != raw
            or cleared_raw != b""
        ):
            raise KnowledgeWriteConflict(
                f"atomic append app-local state changed after transition for "
                f"{authority.note_rel_path}"
            )
    finally:
        os.close(state_fd)
        os.close(swap_fd)


def _bind_host_append_route(authority: _AtomicAppendAuthority) -> None:
    """Bind one caller route immutably to its opened resource identity."""

    route_key = authority.route_key
    route_state_name, route_swap_name = _host_append_route_names(route_key)
    expected_payload: dict[str, object] = {
        "schema": _HOST_APPEND_ROUTE_SCHEMA,
        "route_key": route_key,
        "locator": authority.note_rel_path,
        "resource_keys": sorted(authority.host_state_keys),
        "root_dev": authority.root_stat.st_dev,
        "root_ino": authority.root_stat.st_ino,
    }
    fence_fd = _open_durable_host_fence_root(authority)
    try:
        witness_fd = dict(authority.host_witness_fds).get(route_key)
        if witness_fd is None:
            raise AssertionError("atomic append route witness authority is not bound")
        state_record = _read_host_state_record(
            fence_fd,
            authority,
            route_key,
            route_state_name,
            decode=False,
        )
        swap_record = _read_host_state_record(
            fence_fd,
            authority,
            route_key,
            route_swap_name,
            decode=False,
        )
        candidates: list[bytes] = []
        for raw in (state_record.raw, swap_record.raw):
            if raw:
                candidates.append(raw)
        witness_copy = os.dup(witness_fd)
        try:
            witness_raw = _read_all(witness_copy)
        finally:
            os.close(witness_copy)
        all_candidates = [*candidates]
        if witness_raw:
            all_candidates.append(witness_raw)
        if all_candidates:
            try:
                decoded = [json.loads(raw) for raw in all_candidates]
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise KnowledgeWriteConflict(
                    f"atomic append app-local route is malformed for "
                    f"{authority.note_rel_path}; reconciliation is required before retry"
                ) from exc
            if any(candidate != expected_payload for candidate in decoded):
                raise KnowledgeWriteConflict(
                    f"atomic append app-local route changed for "
                    f"{authority.note_rel_path}; reconciliation is required before retry"
                )
        if not witness_raw:
            authority.assert_host_witness_live()
            _write_host_witness_state(witness_fd, expected_payload)

        if not candidates:
            _write_host_append_state(
                fence_fd,
                authority,
                route_key,
                expected_payload,
                state_record,
                swap_record,
                state_name=route_state_name,
                swap_name=route_swap_name,
            )
        authority.assert_host_witness_live()
    finally:
        os.close(fence_fd)


def _write_host_append_states(
    authority: _AtomicAppendAuthority,
    payload: dict[str, object],
    *,
    allow_reconciled_clean: bool = False,
) -> None:
    fence_fd = _open_durable_host_fence_root(authority)
    try:
        authority.assert_host_witness_live()
        path_lock_keys = list(authority.host_state_keys)
        if payload.get("state") == "clean":
            # Keep the canonical/referent key active until every lexical alias
            # has its clean receipt. Crash between writes therefore leaves a
            # state every alias will reconcile rather than bypass.
            path_lock_keys = [
                key
                for key in path_lock_keys
                if key != authority.canonical_path_lock_key
            ] + [authority.canonical_path_lock_key]
        witness_fds = dict(authority.host_witness_fds)
        if any(key not in witness_fds for key in path_lock_keys):
            raise AssertionError("atomic append host witness authority is not bound")

        if payload.get("state") == "indeterminate":
            record_snapshots = {
                path_lock_key: (
                    _read_host_append_record(
                        fence_fd,
                        authority,
                        path_lock_key,
                        decode=False,
                    ),
                    _read_host_swap_record(
                        fence_fd,
                        authority,
                        path_lock_key,
                        decode=False,
                    ),
                )
                for path_lock_key in path_lock_keys
            }
        else:
            inventories = _read_host_append_inventories(fence_fd, authority)
            _validate_host_append_inventories(
                authority,
                inventories,
            )
            if payload.get("state") == "clean" and not allow_reconciled_clean:
                transaction = payload.get("transaction")
                if any(
                    record.state is not None
                    and record.state.get("transaction") != transaction
                    for (
                        _path_lock_key,
                        app_record,
                        swap_record,
                        _witness_state,
                    ) in inventories
                    for record in (app_record, swap_record)
                ):
                    raise KnowledgeWriteConflict(
                        f"atomic append app-local state transaction changed for "
                        f"{authority.note_rel_path}; reconciliation is required "
                        "before retry"
                    )
            record_snapshots = {
                path_lock_key: (app_record, swap_record)
                for (
                    path_lock_key,
                    app_record,
                    swap_record,
                    _witness_state,
                ) in inventories
            }

        keyed_payloads = {
            path_lock_key: {
                **payload,
                "schema": _HOST_APPEND_STATE_SCHEMA,
                "path_lock_key": path_lock_key,
                "locator": authority.note_rel_path,
                "authority_keys": sorted(authority.host_state_keys),
            }
            for path_lock_key in path_lock_keys
        }

        if payload.get("state") != "clean":
            # The already-required host-lock files are the independent restart
            # witness. They become active/indeterminate before app-local state,
            # so replacement of either namespace cannot erase publication intent.
            for path_lock_key in path_lock_keys:
                authority.assert_host_witness_live()
                _write_host_witness_state(
                    witness_fds[path_lock_key],
                    keyed_payloads[path_lock_key],
                )
        for path_lock_key in path_lock_keys:
            expected_state, expected_swap = record_snapshots[path_lock_key]
            _write_host_append_state(
                fence_fd,
                authority,
                path_lock_key,
                keyed_payloads[path_lock_key],
                expected_state,
                expected_swap,
            )
        if payload.get("state") == "clean":
            # Clean reaches the independent witness last. A crash during the
            # app-local clean writes therefore leaves an active witness.
            for path_lock_key in path_lock_keys:
                authority.assert_host_witness_live()
                _write_host_witness_state(
                    witness_fds[path_lock_key],
                    keyed_payloads[path_lock_key],
                )
        _read_all_host_append_states(fence_fd, authority)
        authority.assert_host_witness_live()
    finally:
        os.close(fence_fd)


def _read_host_append_inventories(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
) -> list[
    tuple[
        str,
        _HostStateRecord,
        _HostStateRecord,
        dict[str, object] | None,
    ]
]:
    authority.assert_host_witness_live()
    witness_fds = dict(authority.host_witness_fds)
    inventories: list[
        tuple[
            str,
            _HostStateRecord,
            _HostStateRecord,
            dict[str, object] | None,
        ]
    ] = []
    for path_lock_key in authority.host_state_keys:
        witness_fd = witness_fds.get(path_lock_key)
        if witness_fd is None:
            raise AssertionError("atomic append host witness authority is not bound")
        app_record = _read_host_append_record(
            fence_fd,
            authority,
            path_lock_key,
        )
        swap_record = _read_host_swap_record(
            fence_fd,
            authority,
            path_lock_key,
        )
        witness_state = _read_host_witness_state(
            witness_fd,
            authority,
            path_lock_key,
        )
        inventories.append(
            (
                path_lock_key,
                app_record,
                swap_record,
                witness_state,
            )
        )
    return inventories


def _validate_host_append_inventories(
    authority: _AtomicAppendAuthority,
    inventories: list[
        tuple[
            str,
            _HostStateRecord,
            _HostStateRecord,
            dict[str, object] | None,
        ]
    ],
    *,
    allow_complete_active_witness_without_app: bool = False,
) -> list[dict[str, object]]:
    inventory_records = [
        (
            [
                state
                for state in (app_record.state, swap_record.state)
                if state is not None
            ],
            witness_state,
        )
        for _path_lock_key, app_record, swap_record, witness_state in inventories
    ]
    normalized_active_witnesses = [
        {key: value for key, value in witness_state.items() if key != "path_lock_key"}
        for _app_states, witness_state in inventory_records
        if witness_state is not None and witness_state.get("state") == "active"
    ]
    has_missing_app_state = any(
        not app_states and witness_state is not None
        for app_states, witness_state in inventory_records
    )
    complete_active_witness_set = (
        allow_complete_active_witness_without_app
        and has_missing_app_state
        and len(normalized_active_witnesses) == len(inventory_records)
        and bool(normalized_active_witnesses)
        and all(
            candidate == normalized_active_witnesses[0]
            for candidate in normalized_active_witnesses[1:]
        )
    )
    if complete_active_witness_set:
        for app_states, witness_state in inventory_records:
            if witness_state is None:
                raise AssertionError("complete active witness set lost one witness")
            normalized_witness = {
                key: value
                for key, value in witness_state.items()
                if key != "path_lock_key"
            }
            if any(
                state.get("state") != "active"
                or {
                    key: value
                    for key, value in state.items()
                    if key != "path_lock_key"
                }
                != normalized_witness
                for state in app_states
            ):
                raise KnowledgeWriteConflict(
                    f"atomic append partial app-local state does not match its "
                    f"active witness for {authority.note_rel_path}; "
                    "reconciliation is required before retry"
                )
    if any(app_states or witness_state is not None for app_states, witness_state in inventory_records):
        if any(
            not app_states and witness_state is None
            for app_states, witness_state in inventory_records
        ):
            raise KnowledgeWriteConflict(
                f"atomic append app-local state is missing for "
                f"{authority.note_rel_path}; reconciliation is required before retry"
            )

    states: list[dict[str, object]] = []
    for app_states, witness_state in inventory_records:
        if app_states and witness_state is None:
            if any(state.get("state") != "clean" for state in app_states):
                raise KnowledgeWriteConflict(
                    f"atomic append host witness is missing for "
                    f"{authority.note_rel_path}; reconciliation is required before retry"
                )
        if (
            witness_state is not None
            and not app_states
            and not complete_active_witness_set
        ):
            raise KnowledgeWriteConflict(
                f"atomic append app-local state is missing for "
                f"{authority.note_rel_path}; reconciliation is required before retry"
            )
        records = [*app_states]
        if witness_state is not None:
            records.append(witness_state)

        active_transactions = {
            str(state.get("transaction"))
            for state in records
            if state.get("state") == "active"
        }
        clean_transactions = {
            str(state.get("transaction"))
            for state in records
            if state.get("state") == "clean"
        }
        if len(active_transactions) > 1 or (
            not active_transactions and len(clean_transactions) > 1
        ):
            raise KnowledgeWriteConflict(
                f"atomic append paired host state is mismatched for "
                f"{authority.note_rel_path}; reconciliation is required before retry"
            )
        grouped: dict[tuple[object, object], list[dict[str, object]]] = {}
        for state in records:
            grouped.setdefault(
                (state.get("state"), state.get("transaction")),
                [],
            ).append(state)
        if any(
            any(candidate != group[0] for candidate in group[1:])
            for group in grouped.values()
        ):
            raise KnowledgeWriteConflict(
                f"atomic append paired host state payload is mismatched for "
                f"{authority.note_rel_path}; reconciliation is required before retry"
            )
        states.extend(records)
    active_transactions = {
        str(state.get("transaction"))
        for state in states
        if state.get("state") == "active"
    }
    clean_transactions = {
        str(state.get("transaction"))
        for state in states
        if state.get("state") == "clean"
    }
    if len(active_transactions) > 1 or (
        not active_transactions and len(clean_transactions) > 1
    ):
        raise KnowledgeWriteConflict(
            f"atomic append paired host state has conflicting transactions for "
            f"{authority.note_rel_path}; reconciliation is required before retry"
        )
    normalized_groups: dict[
        tuple[object, object],
        list[dict[str, object]],
    ] = {}
    for state in states:
        normalized = {key: value for key, value in state.items() if key != "path_lock_key"}
        normalized_groups.setdefault(
            (state.get("state"), state.get("transaction")),
            [],
        ).append(normalized)
    if any(
        any(candidate != group[0] for candidate in group[1:])
        for group in normalized_groups.values()
    ):
        raise KnowledgeWriteConflict(
            f"atomic append paired host state payloads conflict across aliases for "
            f"{authority.note_rel_path}; reconciliation is required before retry"
        )
    return states


def _read_all_host_append_states(
    fence_fd: int,
    authority: _AtomicAppendAuthority,
    *,
    allow_complete_active_witness_without_app: bool = False,
) -> list[dict[str, object]]:
    inventories = _read_host_append_inventories(fence_fd, authority)
    return _validate_host_append_inventories(
        authority,
        inventories,
        allow_complete_active_witness_without_app=(
            allow_complete_active_witness_without_app
        ),
    )


def _repair_missing_active_app_records(authority: _AtomicAppendAuthority) -> None:
    """Restore only missing app copies from a complete exact active witness set."""

    fence_fd = _open_durable_host_fence_root(authority)
    try:
        inventories = _read_host_append_inventories(fence_fd, authority)
        _validate_host_append_inventories(
            authority,
            inventories,
            allow_complete_active_witness_without_app=True,
        )
        for (
            path_lock_key,
            app_record,
            swap_record,
            witness_state,
        ) in inventories:
            if app_record.state is not None or swap_record.state is not None:
                continue
            if witness_state is None or witness_state.get("state") != "active":
                raise KnowledgeWriteConflict(
                    f"atomic append active witness set changed for "
                    f"{authority.note_rel_path}; reconciliation is required before retry"
                )
            _write_host_append_state(
                fence_fd,
                authority,
                path_lock_key,
                witness_state,
                app_record,
                swap_record,
            )
        _read_all_host_append_states(fence_fd, authority)
    finally:
        os.close(fence_fd)


def _require_no_host_indeterminate_fence(authority: _AtomicAppendAuthority) -> None:
    """Precommit the durable namespace and reject stale/indeterminate roots."""

    fence_fd = _open_durable_host_fence_root(authority)
    try:
        for state in _read_all_host_append_states(
            fence_fd,
            authority,
            allow_complete_active_witness_without_app=True,
        ):
            if state["state"] == "indeterminate" or (
                state.get("root_dev") != authority.root_stat.st_dev
                or state.get("root_ino") != authority.root_stat.st_ino
            ):
                raise KnowledgeWriteConflict(
                    f"atomic append authority mapping is indeterminate for "
                    f"{authority.note_rel_path}; reconciliation is required before retry"
                )
    finally:
        os.close(fence_fd)


def _host_append_state_exists(authority: _AtomicAppendAuthority) -> bool:
    fence_fd = _open_durable_host_fence_root(authority)
    try:
        return bool(
            _read_all_host_append_states(
                fence_fd,
                authority,
                allow_complete_active_witness_without_app=True,
            )
        )
    finally:
        os.close(fence_fd)


def _mark_host_atomic_append_indeterminate(
    authority: _AtomicAppendAuthority,
    transaction_id: str,
    reason: str,
) -> None:
    _write_host_append_states(
        authority,
        {
            "state": "indeterminate",
            "transaction": transaction_id,
            "root_dev": authority.root_stat.st_dev,
            "root_ino": authority.root_stat.st_ino,
            "reason": reason,
        },
    )


def _host_mapping_payload(
    authority: _AtomicAppendAuthority,
    parent_fd: int,
    recovery_fd: int,
) -> dict[str, object]:
    parent = os.fstat(parent_fd)
    recovery = os.fstat(recovery_fd)
    return {
        "root_dev": authority.root_stat.st_dev,
        "root_ino": authority.root_stat.st_ino,
        "parent_dev": parent.st_dev,
        "parent_ino": parent.st_ino,
        "recovery_dev": recovery.st_dev,
        "recovery_ino": recovery.st_ino,
    }


def _host_target_payload(parent_fd: int, target_name: str) -> dict[str, object]:
    try:
        target_fd = os.open(
            target_name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return {"target_present": False}
    except OSError as exc:
        raise KnowledgeWriteConflict(
            "atomic append host state target cannot be reconciled"
        ) from exc
    try:
        target = os.fstat(target_fd)
        if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
            raise KnowledgeWriteConflict(
                "atomic append host state target cannot be reconciled"
            )
        payload, metadata = _read_bound_file(
            target_fd,
            target,
            context="atomic append host state target",
        )
    finally:
        os.close(target_fd)
    return {
        "target_present": True,
        "target_dev": target.st_dev,
        "target_ino": target.st_ino,
        "target_digest": hashlib.sha256(payload).hexdigest(),
        "target_metadata": _access_metadata_host_payload(metadata),
    }


def _host_mapping_matches(
    state: dict[str, object],
    mapping: dict[str, object],
) -> bool:
    return all(state.get(key) == value for key, value in mapping.items())


def _latest_original_host_payload(
    entry: _RecoveryEntry | None,
) -> dict[str, object]:
    if entry is None:
        return {"latest_original_present": False}
    return {
        "latest_original_present": True,
        "latest_original_dev": entry.identity.st_dev,
        "latest_original_ino": entry.identity.st_ino,
        "latest_original_digest": entry.digest,
        "latest_original_metadata": _access_metadata_host_payload(entry.metadata),
    }


def _next_latest_original_host_payload(
    entry: _RecoveryEntry | None,
) -> dict[str, object]:
    payload = _latest_original_host_payload(entry)
    next_payload = {
        key.replace("latest_original", "next_latest_original", 1): value
        for key, value in payload.items()
    }
    if entry is not None:
        next_payload["next_latest_original_name"] = entry.name
    return next_payload


def _host_latest_original_matches(
    state: dict[str, object],
    payload: dict[str, object],
) -> bool:
    return all(state.get(key) == value for key, value in payload.items())


def _host_next_latest_original_matches(
    state: dict[str, object],
    payload: dict[str, object],
) -> bool:
    expected = {
        key.replace("latest_original", "next_latest_original", 1): value
        for key, value in payload.items()
    }
    return all(state.get(key) == value for key, value in expected.items())


def _host_uses_present_next_latest_original(
    state: dict[str, object],
    payload: dict[str, object],
) -> bool:
    return (
        state.get("next_latest_original_present") is True
        and _host_next_latest_original_matches(state, payload)
    )


def _host_prepared_next_latest_original_is_named(
    recovery_fd: int,
    state: dict[str, object],
) -> bool:
    name = state.get("next_latest_original_name")
    if (
        not isinstance(name, str)
        or not name.startswith(".steering-append-")
        or os.path.basename(name) != name
    ):
        return False
    try:
        prepared_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=recovery_fd,
        )
    except OSError:
        return False
    try:
        observed = os.fstat(prepared_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_dev != state.get("next_latest_original_dev")
            or observed.st_ino != state.get("next_latest_original_ino")
        ):
            return False
        payload, metadata = _read_bound_file(
            prepared_fd,
            observed,
            context="atomic append prepared latest-original",
        )
        return (
            hashlib.sha256(payload).hexdigest()
            == state.get("next_latest_original_digest")
            and _access_metadata_host_payload(metadata)
            == state.get("next_latest_original_metadata")
        )
    finally:
        os.close(prepared_fd)


def _host_prepared_proposal_is_named(
    parent_fd: int,
    state: dict[str, object],
) -> bool:
    name = state.get("proposal_name")
    if (
        not isinstance(name, str)
        or not name.startswith(".atomic-append-")
        or not name.endswith(".stage")
        or os.path.basename(name) != name
    ):
        return False
    try:
        proposal_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except OSError:
        return False
    try:
        observed = os.fstat(proposal_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_dev != state.get("proposal_dev")
            or observed.st_ino != state.get("proposal_ino")
        ):
            return False
        payload, metadata = _read_bound_file(
            proposal_fd,
            observed,
            context="atomic append prepared proposal",
        )
        return (
            hashlib.sha256(payload).hexdigest() == state.get("proposal_digest")
            and _access_metadata_host_payload(metadata)
            == state.get("proposal_metadata")
        )
    finally:
        os.close(proposal_fd)


def _open_latest_original_snapshot(
    recovery_fd: int,
    note_rel_path: str,
) -> _RecoveryEntry | None:
    name = _latest_original_recovery_name(note_rel_path)
    try:
        snapshot_fd = os.open(
            name,
            os.O_RDWR
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=recovery_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise KnowledgeWriteConflict(
            "atomic append latest-original slot cannot be authenticated"
        ) from exc
    try:
        observed = os.fstat(snapshot_fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise KnowledgeWriteConflict(
                "atomic append latest-original slot must be one regular file"
            )
        payload, metadata = _read_bound_file(
            snapshot_fd,
            observed,
            context="atomic append prior latest-original slot",
        )
        return _RecoveryEntry(
            name=name,
            identity=observed,
            digest=hashlib.sha256(payload).hexdigest(),
            metadata=metadata,
            fd=snapshot_fd,
        )
    except BaseException:
        os.close(snapshot_fd)
        raise


def _reconcile_host_atomic_append_states(
    authority: _AtomicAppendAuthority,
    parent_fd: int,
    recovery_fd: int,
    target_name: str,
) -> dict[str, object]:
    """Converge a crash-precommitted active intent or fail permanently closed."""

    mapping = _host_mapping_payload(authority, parent_fd, recovery_fd)
    fence_fd = _open_durable_host_fence_root(authority)
    observed_latest: _RecoveryEntry | None = None
    saw_active = False
    active_states: list[dict[str, object]] = []
    transaction = "reconciled"
    reason: str | None = None
    missing_app_state = False
    try:
        observed_latest = _open_latest_original_snapshot(
            recovery_fd,
            authority.note_rel_path,
        )
        latest_payload = _latest_original_host_payload(observed_latest)
        inventories = _read_host_append_inventories(fence_fd, authority)
        missing_app_state = any(
            app_record.state is None and swap_record.state is None
            for (
                _path_lock_key,
                app_record,
                swap_record,
                witness_state,
            ) in inventories
            if witness_state is not None
        )
        states = _validate_host_append_inventories(
            authority,
            inventories,
            allow_complete_active_witness_without_app=True,
        )
        if not states and latest_payload["latest_original_present"] is True:
            reason = "latest-original slot has no durable host record"
        matching_clean_transactions = {
            str(state.get("transaction"))
            for state in states
            if state.get("state") == "clean"
            and _host_latest_original_matches(state, latest_payload)
        }
        for state in states:
            transaction = str(state.get("transaction", transaction))
            if state["state"] == "indeterminate":
                reason = "prior host state is indeterminate"
                break
            latest_matches_prior = _host_latest_original_matches(
                state,
                latest_payload,
            )
            if (
                state["state"] == "active"
                and latest_matches_prior
                and state.get("latest_original_present") is False
                and state.get("next_latest_original_present") is True
                and not _host_prepared_next_latest_original_is_named(
                    recovery_fd,
                    state,
                )
            ):
                reason = "prepared latest-original phase evidence is missing"
                break
            if not latest_matches_prior and not (
                state["state"] == "active"
                and (
                    transaction in matching_clean_transactions
                    or _host_uses_present_next_latest_original(
                        state,
                        latest_payload,
                    )
                )
            ):
                reason = "latest-original slot changed from durable host record"
                break
            if not _host_mapping_matches(state, mapping):
                reason = "host state authority mapping changed"
                break
            if state["state"] == "clean":
                continue
            saw_active = True
            active_states.append(state)
    finally:
        os.close(fence_fd)
        if observed_latest is not None:
            os.close(observed_latest.fd)

    target: dict[str, object] = {}
    if reason is None and saw_active:
        target = _host_target_payload(parent_fd, target_name)
        for state in active_states:
            proposal_matches = (
                target.get("target_present") is True
                and target.get("target_dev") == state.get("proposal_dev")
                and target.get("target_ino") == state.get("proposal_ino")
                and target.get("target_digest") == state.get("proposal_digest")
                and target.get("target_metadata")
                == state.get("proposal_metadata")
            )
            original_matches = (
                state.get("source_present") is False
                and target.get("target_present") is False
            ) or (
                state.get("source_present") is True
                and target.get("target_present") is True
                and target.get("target_dev") == state.get("source_dev")
                and target.get("target_ino") == state.get("source_ino")
                and target.get("target_digest") == state.get("source_digest")
                and target.get("target_metadata")
                == state.get("source_metadata")
            )
            if (
                original_matches
                and not proposal_matches
                and not _host_prepared_proposal_is_named(parent_fd, state)
            ):
                reason = "prepared proposal phase evidence is missing"
                break
            if missing_app_state and not original_matches:
                reason = (
                    "app-local state is missing outside the authenticated "
                    "prepublication phase"
                )
                break
            if _host_uses_present_next_latest_original(
                state,
                latest_payload,
            ) and not proposal_matches:
                reason = "latest-original rotation precedes canonical proposal"
                break
            if not proposal_matches and not original_matches:
                reason = "active host intent matches neither proposal nor original"
                break

    if reason is not None:
        if missing_app_state:
            raise KnowledgeWriteConflict(
                f"atomic append app-local state is missing for "
                f"{authority.note_rel_path}; reconciliation is required before retry"
            )
        _mark_host_atomic_append_indeterminate(authority, transaction, reason)
        raise KnowledgeWriteConflict(
            f"atomic append authority mapping is indeterminate for "
            f"{authority.note_rel_path}; reconciliation is required before retry"
        )
    if saw_active:
        if missing_app_state:
            _repair_missing_active_app_records(authority)
        _write_host_append_states(
            authority,
            {
                "state": "clean",
                "transaction": transaction,
                **mapping,
                **target,
                **latest_payload,
                "reason": "reconciled crash-precommitted intent",
            },
            allow_reconciled_clean=True,
        )
    return latest_payload


def _prepare_host_atomic_append_intent(
    authority: _AtomicAppendAuthority,
    parent_fd: int,
    recovery_fd: int,
    *,
    transaction_id: str,
    source_stat: os.stat_result | None,
    source_digest: str | None,
    source_metadata: _AccessMetadata | None,
    proposal_stat: os.stat_result,
    proposal_digest: str,
    proposal_metadata: _AccessMetadata,
    proposal_name: str,
    prior_latest_original: _RecoveryEntry | None,
    next_latest_original: _RecoveryEntry | None,
) -> None:
    source: dict[str, object]
    if source_stat is None:
        source = {"source_present": False}
    else:
        if source_metadata is None:
            raise AssertionError("existing source lost access metadata authority")
        source = {
            "source_present": True,
            "source_dev": source_stat.st_dev,
            "source_ino": source_stat.st_ino,
            "source_digest": source_digest,
            "source_metadata": _access_metadata_host_payload(source_metadata),
        }
    _write_host_append_states(
        authority,
        {
            "state": "active",
            "transaction": transaction_id,
            **_host_mapping_payload(authority, parent_fd, recovery_fd),
            **source,
            "proposal_dev": proposal_stat.st_dev,
            "proposal_ino": proposal_stat.st_ino,
            "proposal_digest": proposal_digest,
            "proposal_metadata": _access_metadata_host_payload(proposal_metadata),
            "proposal_name": proposal_name,
            **_latest_original_host_payload(prior_latest_original),
            **_next_latest_original_host_payload(next_latest_original),
        },
    )


def _complete_host_atomic_append_intent(
    authority: _AtomicAppendAuthority,
    parent_fd: int,
    recovery_fd: int,
    target_name: str,
    transaction_id: str,
    latest_original: _RecoveryEntry | None,
) -> None:
    _write_host_append_states(
        authority,
        {
            "state": "clean",
            "transaction": transaction_id,
            **_host_mapping_payload(authority, parent_fd, recovery_fd),
            **_host_target_payload(parent_fd, target_name),
            **_latest_original_host_payload(latest_original),
        },
    )


def _mark_atomic_append_indeterminate(
    authority: _AtomicAppendAuthority,
    recovery_fd: int,
    note_rel_path: str,
    transaction_id: str,
    reason: str,
) -> None:
    # The crash-precommitted host state already blocks ambiguous retry. Try
    # both durable receipts independently so failure of one authority cannot
    # suppress the other.
    host_error: BaseException | None = None
    try:
        _mark_host_atomic_append_indeterminate(authority, transaction_id, reason)
    except BaseException as exc:  # noqa: BLE001 - preserve after root receipt attempt
        host_error = exc
    name = (
        f"{_indeterminate_marker_prefix(note_rel_path)}"
        f"{transaction_id}.md.conflict"
    )
    try:
        marker_fd = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=recovery_fd,
        )
    except FileExistsError:
        if host_error is not None:
            raise host_error
        return
    try:
        payload = (
            f"transaction={transaction_id}\nlocator={note_rel_path}\nreason={reason}\n"
        ).encode("utf-8")
        _write_all(marker_fd, payload)
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)
    os.fsync(recovery_fd)
    if host_error is not None:
        raise host_error


def _recovery_name(
    *,
    transaction_id: str,
    role: str,
    digest: str,
    identity: os.stat_result,
) -> str:
    return (
        f".steering-append-{transaction_id}-{role}-{digest}-"
        f"{identity.st_dev}-{identity.st_ino}.md.conflict"
    )


def _publish_recovery_snapshot(
    source_fd: int,
    expected: os.stat_result,
    recovery_fd: int,
    *,
    transaction_id: str,
    role: str,
    allow_unlinked_source: bool = False,
) -> _RecoveryEntry:
    """Durably publish a snapshot and transfer its writable fd to the caller."""

    payload, metadata = _read_bound_file(
        source_fd,
        expected,
        context=f"atomic append {role} recovery source",
    )
    digest = hashlib.sha256(payload).hexdigest()
    final_name = _recovery_name(
        transaction_id=transaction_id,
        role=role,
        digest=digest,
        identity=expected,
    )
    temp_name = (
        f".atomic-append-recovery-{transaction_id}-{role}-{uuid.uuid4().hex}.tmp"
    )
    snapshot_fd = os.open(
        temp_name,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=recovery_fd,
    )
    try:
        _write_all(snapshot_fd, payload)
        _copy_access_metadata(
            source_fd,
            snapshot_fd,
            allow_unlinked_source=allow_unlinked_source,
        )
        os.fsync(snapshot_fd)
        snapshot_stat = os.fstat(snapshot_fd)
        snapshot_payload, snapshot_metadata = _read_bound_file(
            snapshot_fd,
            snapshot_stat,
            context=f"atomic append {role} recovery snapshot",
        )
        if snapshot_payload != payload or snapshot_metadata != metadata:
            raise KnowledgeWriteConflict(
                f"atomic append {role} recovery snapshot changed before publication"
            )
        _atomic_rename_noreplace_at(
            recovery_fd,
            temp_name,
            recovery_fd,
            final_name,
        )
        os.fsync(recovery_fd)
        published = os.stat(final_name, dir_fd=recovery_fd, follow_symlinks=False)
        if not _same_file_identity(published, snapshot_stat):
            raise KnowledgeWriteConflict(
                f"atomic append {role} recovery identity changed during publication"
            )
        entry = _RecoveryEntry(
            name=final_name,
            identity=snapshot_stat,
            digest=digest,
            metadata=metadata,
            fd=snapshot_fd,
        )
    except BaseException:
        os.close(snapshot_fd)
        raise
    return entry


def _move_entry_to_recovery(
    source_fd: int,
    source_name: str,
    expected: os.stat_result,
    recovery_fd: int,
    destination_name: str,
) -> os.stat_result:
    """Atomically retain a named entry under the anchored root recovery dir."""

    _atomic_rename_noreplace_at(
        source_fd,
        source_name,
        recovery_fd,
        destination_name,
    )
    os.fsync(source_fd)
    os.fsync(recovery_fd)
    retained = os.stat(
        destination_name,
        dir_fd=recovery_fd,
        follow_symlinks=False,
    )
    if not _same_file_identity(retained, expected):
        raise KnowledgeWriteConflict(
            "atomic append recovery entry changed during retention"
        )
    return retained


def _quarantine_recovery_temp(recovery_fd: int, name: str) -> None:
    observed = os.stat(name, dir_fd=recovery_fd, follow_symlinks=False)
    destination = f".steering-append-unknown-{uuid.uuid4().hex}.md.conflict"
    _move_entry_to_recovery(
        recovery_fd,
        name,
        observed,
        recovery_fd,
        destination,
    )


def _sweep_atomic_append_recovery_temps(recovery_fd: int) -> None:
    for name in sorted(os.listdir(recovery_fd)):
        if _ATOMIC_APPEND_RECOVERY_TEMP_RE.fullmatch(name):
            _quarantine_recovery_temp(recovery_fd, name)


def _sweep_atomic_append_stages(parent_fd: int, recovery_fd: int) -> None:
    """Move every prior crash-stage out of the canonical parent without deletion."""

    for name in sorted(os.listdir(parent_fd)):
        if not name.startswith(".atomic-append-") or not (
            name.endswith(".stage") or name.endswith(".tmp")
        ):
            continue
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        match = _ATOMIC_APPEND_STAGE_RE.fullmatch(name)
        disposition = "unknown"
        if match and stat.S_ISREG(observed.st_mode):
            stage_fd = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            try:
                payload, _metadata = _read_bound_file(
                    stage_fd,
                    observed,
                    context="atomic append crash stage",
                )
            finally:
                os.close(stage_fd)
            if hashlib.sha256(payload).hexdigest() == match.group("digest"):
                disposition = "owned"
        destination = (
            f".steering-append-{disposition}-stage-{uuid.uuid4().hex}.md.conflict"
        )
        _move_entry_to_recovery(
            parent_fd,
            name,
            observed,
            recovery_fd,
            destination,
        )


def _retire_recovery_entry(recovery_fd: int, entry: _RecoveryEntry) -> None:
    """Quarantine one proven entry without deleting through a mutable name."""

    current = os.fstat(entry.fd)
    payload, metadata = _read_bound_file(
        entry.fd,
        current,
        context="atomic append recovery retirement",
    )
    if (
        not _same_file_identity(current, entry.identity)
        or hashlib.sha256(payload).hexdigest() != entry.digest
        or metadata != entry.metadata
    ):
        raise KnowledgeWriteConflict(
            "atomic append recovery snapshot changed before retirement"
        )
    retirement_name = (
        f".steering-append-retired-{uuid.uuid4().hex}.md.conflict"
    )
    _move_entry_to_recovery(
        recovery_fd,
        entry.name,
        entry.identity,
        recovery_fd,
        retirement_name,
    )
    retired = os.stat(
        retirement_name,
        dir_fd=recovery_fd,
        follow_symlinks=False,
    )
    if not _same_file_identity(retired, entry.identity):
        raise KnowledgeWriteConflict(
            "atomic append recovery snapshot changed during retirement"
        )
    os.fsync(recovery_fd)
    bound_after = os.fstat(entry.fd)
    payload_after, metadata_after = _read_bound_file(
        entry.fd,
        entry.identity,
        context="atomic append recovery descriptor retirement",
    )
    if (
        not _same_file_identity(bound_after, entry.identity)
        or bound_after.st_nlink != 1
        or hashlib.sha256(payload_after).hexdigest() != entry.digest
        or metadata_after != entry.metadata
    ):
        raise KnowledgeWriteConflict(
            "atomic append recovery snapshot changed during descriptor retirement"
        )


def _latest_original_recovery_name(note_rel_path: str) -> str:
    token = hashlib.sha256(note_rel_path.encode("utf-8")).hexdigest()
    return f".steering-append-latest-original-{token}.md.conflict"


def _retain_latest_original_snapshot(
    recovery_fd: int,
    entry: _RecoveryEntry,
    *,
    note_rel_path: str,
    transaction_id: str,
    expected_prior: _RecoveryEntry | None,
    prepared: _RecoveryEntry | None = None,
) -> _RecoveryEntry:
    """Keep one bounded full original, replacing only a proven prior slot."""

    working = prepared
    owns_working = working is None
    if working is None:
        working = _publish_recovery_snapshot(
            entry.fd,
            entry.identity,
            recovery_fd,
            transaction_id=transaction_id,
            role="latestcopy",
            allow_unlinked_source=True,
        )
    try:
        return _retain_named_latest_original_snapshot(
            recovery_fd,
            working,
            note_rel_path=note_rel_path,
            transaction_id=transaction_id,
            expected_prior=expected_prior,
        )
    except BaseException:
        if owns_working:
            os.close(working.fd)
        raise


def _retain_named_latest_original_snapshot(
    recovery_fd: int,
    entry: _RecoveryEntry,
    *,
    note_rel_path: str,
    transaction_id: str,
    expected_prior: _RecoveryEntry | None,
) -> _RecoveryEntry:
    """Move one named exact copy into the bounded latest-original slot."""

    stable_name = _latest_original_recovery_name(note_rel_path)
    if expected_prior is not None:
        _require_named_recovery_entry_live(
            recovery_fd,
            expected_prior,
            context="atomic append authenticated prior latest-original slot",
        )
    try:
        _atomic_rename_noreplace_at(
            recovery_fd,
            entry.name,
            recovery_fd,
            stable_name,
        )
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
    else:
        if expected_prior is not None:
            preserved = _publish_recovery_snapshot(
                expected_prior.fd,
                expected_prior.identity,
                recovery_fd,
                transaction_id=transaction_id,
                role=f"preserved-prior-{uuid.uuid4().hex}",
                allow_unlinked_source=True,
            )
            os.close(preserved.fd)
            raise KnowledgeWriteConflict(
                "atomic append prior latest-original slot disappeared during rotation"
            )
        os.fsync(recovery_fd)
        stable = os.stat(stable_name, dir_fd=recovery_fd, follow_symlinks=False)
        if not _same_file_identity(stable, entry.identity):
            raise KnowledgeWriteConflict(
                "atomic append latest-original slot changed during publication"
            )
        return _RecoveryEntry(
            name=stable_name,
            identity=entry.identity,
            digest=entry.digest,
            metadata=entry.metadata,
            fd=entry.fd,
        )

    if expected_prior is None:
        raise KnowledgeWriteConflict(
            "atomic append latest-original slot appeared without a durable host record"
        )
    _atomic_exchange_at(
        recovery_fd,
        entry.name,
        recovery_fd,
        stable_name,
    )
    os.fsync(recovery_fd)
    installed = os.stat(
        stable_name,
        dir_fd=recovery_fd,
        follow_symlinks=False,
    )
    displaced = os.stat(
        entry.name,
        dir_fd=recovery_fd,
        follow_symlinks=False,
    )
    if (
        not _same_file_identity(installed, entry.identity)
        or not _same_file_identity(displaced, expected_prior.identity)
    ):
        raise KnowledgeWriteConflict(
            "atomic append latest-original slot changed during exchange"
        )
    _retire_recovery_entry(
        recovery_fd,
        _RecoveryEntry(
            name=entry.name,
            identity=expected_prior.identity,
            digest=expected_prior.digest,
            metadata=expected_prior.metadata,
            fd=expected_prior.fd,
        ),
    )

    return _RecoveryEntry(
        name=stable_name,
        identity=entry.identity,
        digest=entry.digest,
        metadata=entry.metadata,
        fd=entry.fd,
    )


def _require_named_recovery_entry_live(
    recovery_fd: int,
    entry: _RecoveryEntry,
    *,
    context: str,
) -> None:
    """Prove that a held recovery descriptor still has its exact durable name."""

    try:
        named = os.stat(entry.name, dir_fd=recovery_fd, follow_symlinks=False)
    except OSError as exc:
        raise KnowledgeWriteConflict(f"{context} is missing") from exc
    bound = os.fstat(entry.fd)
    payload, metadata = _read_bound_file(
        entry.fd,
        entry.identity,
        context=context,
    )
    if (
        not _same_file_identity(named, entry.identity)
        or not _same_file_identity(bound, entry.identity)
        or named.st_nlink != 1
        or bound.st_nlink != 1
        or hashlib.sha256(payload).hexdigest() != entry.digest
        or metadata != entry.metadata
    ):
        raise KnowledgeWriteConflict(f"{context} changed")


def _preserve_unbound_recovery_entry(
    recovery_fd: int,
    entry: _RecoveryEntry,
    *,
    transaction_id: str,
) -> None:
    """Republish a held full copy when its expected durable name was lost."""

    try:
        _require_named_recovery_entry_live(
            recovery_fd,
            entry,
            context="atomic append retained original",
        )
    except KnowledgeWriteConflict:
        preserved = _publish_recovery_snapshot(
            entry.fd,
            entry.identity,
            recovery_fd,
            transaction_id=transaction_id,
            role=f"preserved-original-{uuid.uuid4().hex}",
            allow_unlinked_source=True,
        )
        os.close(preserved.fd)


def _retain_stage_after_failure(
    parent_fd: int,
    stage_name: str,
    expected: os.stat_result,
    recovery_fd: int,
    *,
    transaction_id: str,
) -> None:
    try:
        current = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    role = "owned-stage" if _same_file_identity(current, expected) else "raced-stage"
    destination = (
        f".steering-append-{transaction_id}-{role}-{uuid.uuid4().hex}.md.conflict"
    )
    _move_entry_to_recovery(
        parent_fd,
        stage_name,
        current,
        recovery_fd,
        destination,
    )
    if role != "owned-stage":
        raise KnowledgeWriteConflict(
            "atomic append stage changed before recovery; canonical outcome is indeterminate"
        )


def _require_atomic_append_mapping(
    authority: _AtomicAppendAuthority,
    relative_parent: PurePosixPath,
    parent_fd: int,
    recovery_fd: int,
) -> None:
    authority.assert_live()
    probe_fd = os.dup(authority.root_fd)
    try:
        for component in relative_parent.parts:
            if component in {"", "."}:
                continue
            child_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=probe_fd)
            os.close(probe_fd)
            probe_fd = child_fd
        current_parent = os.fstat(probe_fd)
        anchored_parent = os.fstat(parent_fd)
        current_recovery = os.stat(
            "_conflicts",
            dir_fd=authority.root_fd,
            follow_symlinks=False,
        )
        anchored_recovery = os.fstat(recovery_fd)
        if (
            not _same_file_identity(current_parent, anchored_parent)
            or not _same_file_identity(current_recovery, anchored_recovery)
        ):
            raise KnowledgeWriteConflict(
                f"atomic append authority mapping changed for {authority.note_rel_path}"
            )
    except OSError as exc:
        raise KnowledgeWriteConflict(
            f"atomic append authority mapping changed for {authority.note_rel_path}"
        ) from exc
    finally:
        os.close(probe_fd)


def append_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
    _atomic_transform: AtomicAppendTransform | None = None,
    _atomic_authority: _AtomicAppendAuthority | None = None,
) -> WriteReceipt:
    # Guard-at-seam (#3129): append-only writes share the same production
    # boundary as relative overwrites. Assert before resolving the port so an
    # unhealthy/safe-mode runtime cannot mutate the vault through append.
    # The lazy import preserves the circular-import avoidance used by the
    # sibling write seams above.
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    locator = make_note_locator(note_rel_path)
    if _atomic_transform is not None:
        if _atomic_authority is not None:
            if _atomic_authority.note_rel_path != note_rel_path:
                raise KnowledgeCapabilityError(
                    "atomic append authority does not match the requested locator"
                )
            _atomic_authority.assert_live()
            _atomic_append_note_relative(
                note_rel_path,
                content.encode("utf-8"),
                authority=_atomic_authority,
                transform=_atomic_transform,
            )
        else:
            with _open_atomic_append_authority(vault_root, note_rel_path) as authority:
                _atomic_append_note_relative(
                    note_rel_path,
                    content.encode("utf-8"),
                    authority=authority,
                    transform=_atomic_transform,
                )
        return WriteReceipt(
            operation="append_note",
            locator=locator,
            adapter="fs_vault",
            writer_identity="mimer.runtime",
        )
    resolved_root = Path(vault_root).expanduser().resolve()
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    return port.append_note(locator, content)


def _atomic_append_note_relative(
    note_rel_path: str,
    proposed_append: bytes,
    *,
    authority: _AtomicAppendAuthority,
    transform: AtomicAppendTransform,
) -> None:
    """Publish one root-bound append/bookkeeping transaction or retain recovery."""

    parts = _candidate_relative_parts(note_rel_path)
    if note_rel_path != authority.note_rel_path:
        raise KnowledgeCapabilityError(
            "atomic append authority does not match the requested locator"
        )
    relative_parent = PurePosixPath(*parts[:-1])
    transaction_id = uuid.uuid4().hex
    current_dir_fd: int | None = None
    recovery_fd: int | None = None
    source_fd: int | None = None
    stage_fd: int | None = None
    stage_name: str | None = None
    stage_stat: os.stat_result | None = None
    stage_named = False
    intent_prepared = False
    exchange_completed = False
    target_existed = False
    current_raw: bytes | None = None
    source_stat: os.stat_result | None = None
    source_metadata: _AccessMetadata | None = None
    proposal_snapshot: _RecoveryEntry | None = None
    original_snapshot: _RecoveryEntry | None = None
    prior_latest_original_snapshot: _RecoveryEntry | None = None
    prepared_latest_original_snapshot: _RecoveryEntry | None = None
    latest_original_snapshot: _RecoveryEntry | None = None
    displaced_name: str | None = None
    cleanup_error: BaseException | None = None

    def record_cleanup_error(exc: BaseException) -> None:
        nonlocal cleanup_error
        if cleanup_error is None:
            cleanup_error = exc

    try:
        authority.assert_live()
        _require_no_host_indeterminate_fence(authority)
        host_state_exists = _host_append_state_exists(authority)
        current_dir_fd = os.dup(authority.root_fd)
        for component in parts[:-1]:
            try:
                child_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_dir_fd)
            except FileNotFoundError:
                if host_state_exists:
                    raise KnowledgeWriteConflict(
                        f"atomic append authority mapping changed for {note_rel_path}; "
                        "reconciliation is required before retry"
                    )
                os.mkdir(component, mode=0o777, dir_fd=current_dir_fd)
                # Fence the new directory entry before any child mutation. A
                # prior failed fsync is also repaired by the unconditional
                # fence on every retry below.
                os.fsync(current_dir_fd)
                child_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_dir_fd)
            except OSError as exc:
                raise KnowledgeCapabilityError(
                    f"atomic append parent for {note_rel_path} must be an in-vault non-symlink directory"
                ) from exc
            try:
                os.fsync(current_dir_fd)
            except BaseException:
                os.close(child_fd)
                raise
            superseded_fd = current_dir_fd
            current_dir_fd = child_fd
            os.close(superseded_fd)

        target_name = parts[-1]
        recovery_fd = _open_atomic_append_recovery(
            authority.root_fd,
            create=not host_state_exists,
        )
        _require_atomic_append_mapping(
            authority,
            relative_parent,
            current_dir_fd,
            recovery_fd,
        )
        expected_latest_payload = _reconcile_host_atomic_append_states(
            authority,
            current_dir_fd,
            recovery_fd,
            target_name,
        )
        prior_latest_original_snapshot = _open_latest_original_snapshot(
            recovery_fd,
            note_rel_path,
        )
        if _latest_original_host_payload(
            prior_latest_original_snapshot
        ) != expected_latest_payload:
            raise KnowledgeWriteConflict(
                "atomic append latest-original slot changed after reconciliation"
            )
        _sweep_atomic_append_recovery_temps(recovery_fd)
        _sweep_atomic_append_stages(current_dir_fd, recovery_fd)
        _require_no_indeterminate_marker(recovery_fd, note_rel_path)

        # Fence prior uncertain parent creation, stage recovery, or publication
        # before observing the canonical target.
        os.fsync(current_dir_fd)
        os.fsync(recovery_fd)
        try:
            try:
                source_fd = os.open(
                    target_name,
                    os.O_RDWR
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=current_dir_fd,
                )
            except PermissionError as exc:
                raise KnowledgeCapabilityError(
                    f"atomic append target {note_rel_path} must be writable "
                    "before publication"
                ) from exc
        except FileNotFoundError:
            current_raw = None
        except OSError as exc:
            raise KnowledgeCapabilityError(
                f"atomic append target {note_rel_path} must be a regular non-symlink file"
            ) from exc
        else:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise KnowledgeCapabilityError(
                    f"atomic append target {note_rel_path} must be a regular file"
                )
            if source_stat.st_nlink != 1:
                raise KnowledgeCapabilityError(
                    f"atomic append target {note_rel_path} must not have hard-link aliases"
                )
            target_existed = True
            current_raw, source_metadata = _read_bound_file(
                source_fd,
                source_stat,
                context=f"atomic append target {note_rel_path}",
            )

        replacement, actual_append = transform(current_raw, proposed_append)
        if not isinstance(replacement, bytes) or not isinstance(actual_append, bytes):
            raise TypeError("atomic append transform must return bytes payloads")
        if actual_append not in {b"", proposed_append}:
            raise ValueError("atomic append transform changed the proposed append bytes")

        _replacement_frontmatter, replacement_body = _split_frontmatter_body_bytes(replacement)
        if current_raw is None:
            if actual_append != proposed_append or not replacement_body.endswith(proposed_append):
                raise ValueError("new atomic append transaction did not publish the proposed append")
        else:
            _current_frontmatter, current_body = _split_frontmatter_body_bytes(current_raw)
            if replacement_body != current_body + actual_append:
                raise ValueError("atomic append transform changed prior body bytes")

        replacement_digest = hashlib.sha256(replacement).hexdigest()
        source_token = (
            f"{source_stat.st_dev}-{source_stat.st_ino}"
            if source_stat is not None
            else "absent"
        )
        stage_name = (
            f".atomic-append-{transaction_id}-{replacement_digest}-{source_token}.stage"
        )
        stage_fd = os.open(
            stage_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=current_dir_fd,
        )
        stage_named = True
        stage_stat = os.fstat(stage_fd)
        _write_all(stage_fd, replacement)
        if source_fd is not None:
            # Payload I/O precedes metadata cloning because writes can clear
            # special mode bits on macOS and chown can clear them elsewhere.
            _copy_access_metadata(source_fd, stage_fd)
        os.fsync(stage_fd)
        os.fsync(current_dir_fd)
        staged_raw, staged_metadata = _read_bound_file(
            stage_fd,
            stage_stat,
            context=f"atomic append proposal {note_rel_path}",
        )
        if staged_raw != replacement:
            raise KnowledgeWriteConflict(
                f"atomic append proposal changed before publication for {note_rel_path}"
            )
        if source_metadata is not None and staged_metadata != source_metadata:
            raise KnowledgeCapabilityError(
                "atomic append proposal access metadata was not preserved exactly"
            )

        proposal_snapshot = _publish_recovery_snapshot(
            stage_fd,
            stage_stat,
            recovery_fd,
            transaction_id=transaction_id,
            role="proposal",
        )
        if source_fd is not None and source_stat is not None:
            original_snapshot = _publish_recovery_snapshot(
                source_fd,
                source_stat,
                recovery_fd,
                transaction_id=transaction_id,
                role="original",
            )
            prepared_latest_original_snapshot = _publish_recovery_snapshot(
                original_snapshot.fd,
                original_snapshot.identity,
                recovery_fd,
                transaction_id=transaction_id,
                role="latestcopy",
            )

        _require_atomic_append_mapping(
            authority,
            relative_parent,
            current_dir_fd,
            recovery_fd,
        )
        # Once intent preparation starts, the exact named stage is part of
        # restart reconciliation even if a later publication call returns an
        # ordinary error. Cleanup must not rename it out from under that
        # durable record.
        intent_prepared = True
        _prepare_host_atomic_append_intent(
            authority,
            current_dir_fd,
            recovery_fd,
            transaction_id=transaction_id,
            source_stat=source_stat,
            source_digest=(
                hashlib.sha256(current_raw).hexdigest()
                if current_raw is not None
                else None
            ),
            source_metadata=source_metadata,
            proposal_stat=stage_stat,
            proposal_digest=replacement_digest,
            proposal_metadata=staged_metadata,
            proposal_name=stage_name,
            prior_latest_original=prior_latest_original_snapshot,
            next_latest_original=prepared_latest_original_snapshot,
        )

        if target_existed:
            if source_fd is None or source_stat is None or source_metadata is None:
                raise AssertionError("existing atomic append target lost its source authority")
            live = os.stat(
                target_name,
                dir_fd=current_dir_fd,
                follow_symlinks=False,
            )
            latest_raw, latest_metadata = _read_bound_file(
                source_fd,
                source_stat,
                context=f"atomic append target {note_rel_path}",
            )
            if (
                not _same_file_identity(live, source_stat)
                or latest_raw != current_raw
                or latest_metadata != source_metadata
            ):
                raise KnowledgeWriteConflict(
                    f"atomic append target changed before publication for {note_rel_path}"
                )
            _atomic_exchange_at(
                current_dir_fd,
                target_name,
                current_dir_fd,
                stage_name,
            )
            exchange_completed = True
            os.fsync(current_dir_fd)

            published = os.stat(
                target_name,
                dir_fd=current_dir_fd,
                follow_symlinks=False,
            )
            displaced = os.stat(
                stage_name,
                dir_fd=current_dir_fd,
                follow_symlinks=False,
            )
            published_raw, published_metadata = _read_bound_file(
                stage_fd,
                stage_stat,
                context=f"atomic append published proposal {note_rel_path}",
            )
            displaced_raw, displaced_metadata = _read_bound_file(
                source_fd,
                source_stat,
                context=f"atomic append displaced target {note_rel_path}",
            )
            if (
                not _same_file_identity(published, stage_stat)
                or not _same_file_identity(displaced, source_stat)
                or published_raw != replacement
                or published_metadata != staged_metadata
                or displaced_raw != current_raw
                or displaced_metadata != source_metadata
            ):
                _mark_atomic_append_indeterminate(
                    authority,
                    recovery_fd,
                    note_rel_path,
                    transaction_id,
                    "atomic exchange did not bind the checked proposal and original",
                )
                raise KnowledgeWriteConflict(
                    f"atomic append exchange raced for {note_rel_path}; canonical outcome is indeterminate"
                )
        else:
            try:
                _atomic_rename_noreplace_at(
                    current_dir_fd,
                    stage_name,
                    current_dir_fd,
                    target_name,
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise KnowledgeWriteConflict(
                        f"atomic append target appeared during publication for {note_rel_path}"
                    ) from exc
                raise
            exchange_completed = True
            stage_named = False
            os.fsync(current_dir_fd)
            published = os.stat(
                target_name,
                dir_fd=current_dir_fd,
                follow_symlinks=False,
            )
            published_raw, published_metadata = _read_bound_file(
                stage_fd,
                stage_stat,
                context=f"atomic append published proposal {note_rel_path}",
            )
            if (
                not _same_file_identity(published, stage_stat)
                or published_raw != replacement
                or published_metadata != staged_metadata
            ):
                _mark_atomic_append_indeterminate(
                    authority,
                    recovery_fd,
                    note_rel_path,
                    transaction_id,
                    "initial publication identity or content changed",
                )
                raise KnowledgeWriteConflict(
                    f"atomic append initial publication changed for {note_rel_path}; canonical outcome is indeterminate"
                )

        os.fsync(current_dir_fd)
        try:
            _require_atomic_append_mapping(
                authority,
                relative_parent,
                current_dir_fd,
                recovery_fd,
            )
        except KnowledgeWriteConflict as exc:
            _mark_atomic_append_indeterminate(
                authority,
                recovery_fd,
                note_rel_path,
                transaction_id,
                "root or parent authority mapping changed after publication",
            )
            raise KnowledgeWriteConflict(
                f"atomic append authority mapping indeterminate for {note_rel_path}; recovery retained"
            ) from exc

        if target_existed:
            if (
                source_fd is None
                or source_stat is None
                or source_metadata is None
                or current_raw is None
            ):
                raise AssertionError("existing target lost displaced-version authority")
            displaced_name = (
                f".steering-append-{transaction_id}-displaced-{uuid.uuid4().hex}.md.conflict"
            )
            _move_entry_to_recovery(
                current_dir_fd,
                stage_name,
                source_stat,
                recovery_fd,
                displaced_name,
            )
            stage_named = False
            retained_stat = os.stat(
                displaced_name,
                dir_fd=recovery_fd,
                follow_symlinks=False,
            )
            retained_raw, retained_metadata = _read_bound_file(
                source_fd,
                source_stat,
                context=f"atomic append displaced retirement {note_rel_path}",
            )
            if (
                not _same_file_identity(retained_stat, source_stat)
                or retained_raw != current_raw
                or retained_metadata != source_metadata
            ):
                _mark_atomic_append_indeterminate(
                    authority,
                    recovery_fd,
                    note_rel_path,
                    transaction_id,
                    "displaced target changed before clean-success retirement",
                )
                raise KnowledgeWriteConflict(
                    f"atomic append displaced target changed before retirement for {note_rel_path}"
                )
        try:
            _retire_recovery_entry(recovery_fd, proposal_snapshot)
            retired_proposal = proposal_snapshot
            proposal_snapshot = None
            os.close(retired_proposal.fd)
            if original_snapshot is not None:
                latest_original_snapshot = _retain_latest_original_snapshot(
                    recovery_fd,
                    original_snapshot,
                    note_rel_path=note_rel_path,
                    transaction_id=transaction_id,
                    expected_prior=prior_latest_original_snapshot,
                    prepared=prepared_latest_original_snapshot,
                )
                prepared_latest_original_snapshot = None
                if prior_latest_original_snapshot is not None:
                    os.close(prior_latest_original_snapshot.fd)
                    prior_latest_original_snapshot = None
                _require_named_recovery_entry_live(
                    recovery_fd,
                    latest_original_snapshot,
                    context="atomic append latest-original slot",
                )
                _retire_recovery_entry(recovery_fd, original_snapshot)
                retired_original = original_snapshot
                original_snapshot = None
                os.close(retired_original.fd)
                _require_named_recovery_entry_live(
                    recovery_fd,
                    latest_original_snapshot,
                    context="atomic append latest-original slot",
                )
            if target_existed:
                if (
                    source_fd is None
                    or source_stat is None
                    or source_metadata is None
                    or current_raw is None
                    or displaced_name is None
                ):
                    raise AssertionError(
                        "existing target lost bounded original retention authority"
                    )
                _retire_recovery_entry(
                    recovery_fd,
                    _RecoveryEntry(
                        name=displaced_name,
                        identity=source_stat,
                        digest=hashlib.sha256(current_raw).hexdigest(),
                        metadata=source_metadata,
                        fd=source_fd,
                    ),
                )
                if latest_original_snapshot is None:
                    raise AssertionError(
                        "existing target lost latest-original retention authority"
                    )
                _require_named_recovery_entry_live(
                    recovery_fd,
                    latest_original_snapshot,
                    context="atomic append latest-original slot",
                )
        except BaseException as exc:  # noqa: BLE001 - every retirement failure fences
            recovery_entry = latest_original_snapshot or original_snapshot
            if recovery_entry is not None:
                _preserve_unbound_recovery_entry(
                    recovery_fd,
                    recovery_entry,
                    transaction_id=transaction_id,
                )
            _mark_atomic_append_indeterminate(
                authority,
                recovery_fd,
                note_rel_path,
                transaction_id,
                "recovery retirement changed before acknowledgement",
            )
            raise KnowledgeWriteConflict(
                f"atomic append recovery retirement became indeterminate for "
                f"{note_rel_path}"
            ) from exc

        if current_dir_fd is None or recovery_fd is None or stage_fd is None:
            raise AssertionError("atomic append lost receipt descriptors")
        receipt_parent_fd = current_dir_fd
        receipt_recovery_fd = recovery_fd
        receipt_stage_fd = stage_fd

        def require_final_receipt_state() -> None:
            authority.assert_host_state_live()
            authority.assert_host_witness_live()
            _require_no_host_indeterminate_fence(authority)
            live_target = os.stat(
                target_name,
                dir_fd=receipt_parent_fd,
                follow_symlinks=False,
            )
            bound_target = os.fstat(receipt_stage_fd)
            final_raw, final_metadata = _read_bound_file(
                receipt_stage_fd,
                stage_stat,
                context=f"atomic append receipt target {note_rel_path}",
            )
            if (
                not _same_file_identity(live_target, stage_stat)
                or not _same_file_identity(bound_target, stage_stat)
                or not stat.S_ISREG(live_target.st_mode)
                or not stat.S_ISREG(bound_target.st_mode)
                or live_target.st_nlink != 1
                or bound_target.st_nlink != 1
                or final_raw != replacement
                or final_metadata != staged_metadata
            ):
                raise KnowledgeWriteConflict(
                    f"atomic append target changed before acknowledgement for {note_rel_path}"
                )
            _require_atomic_append_mapping(
                authority,
                relative_parent,
                receipt_parent_fd,
                receipt_recovery_fd,
            )
            if latest_original_snapshot is not None:
                _require_named_recovery_entry_live(
                    receipt_recovery_fd,
                    latest_original_snapshot,
                    context="atomic append latest-original receipt slot",
                )
            os.fsync(receipt_parent_fd)

        try:
            # Retirement is complete before the receipt proof. The durable
            # clean host state is then committed, followed by one last proof
            # so a remap during that host commit cannot escape unfenced.
            require_final_receipt_state()
            _complete_host_atomic_append_intent(
                authority,
                current_dir_fd,
                recovery_fd,
                target_name,
                transaction_id,
                latest_original_snapshot,
            )
            require_final_receipt_state()
        except BaseException as exc:  # noqa: BLE001 - every post-publication failure fences
            if latest_original_snapshot is not None:
                _preserve_unbound_recovery_entry(
                    recovery_fd,
                    latest_original_snapshot,
                    transaction_id=transaction_id,
                )
            _mark_atomic_append_indeterminate(
                authority,
                recovery_fd,
                note_rel_path,
                transaction_id,
                "post-publication receipt state changed before acknowledgement",
            )
            raise KnowledgeWriteConflict(
                f"atomic append receipt became indeterminate for {note_rel_path}"
            ) from exc
    finally:
        for snapshot in (
            proposal_snapshot,
            original_snapshot,
            prior_latest_original_snapshot,
            prepared_latest_original_snapshot,
            latest_original_snapshot,
        ):
            if snapshot is not None:
                try:
                    os.close(snapshot.fd)
                except BaseException as exc:  # noqa: BLE001 - preserve recovery authority cleanup
                    record_cleanup_error(exc)
        if stage_fd is not None:
            owned_stage_fd = stage_fd
            stage_fd = None
            try:
                os.close(owned_stage_fd)
            except BaseException as exc:  # noqa: BLE001 - fail-closed ownership cleanup
                record_cleanup_error(exc)
        if (
            stage_named
            and not (intent_prepared and not exchange_completed)
            and stage_name is not None
            and stage_stat is not None
            and current_dir_fd is not None
            and recovery_fd is not None
        ):
            try:
                _retain_stage_after_failure(
                    current_dir_fd,
                    stage_name,
                    stage_stat if not exchange_completed else source_stat or stage_stat,
                    recovery_fd,
                    transaction_id=transaction_id,
                )
                stage_named = False
            except BaseException as exc:  # noqa: BLE001 - cleanup durability is required
                record_cleanup_error(exc)
        if source_fd is not None:
            owned_source_fd = source_fd
            source_fd = None
            try:
                os.close(owned_source_fd)
            except BaseException as exc:  # noqa: BLE001 - preserve the first cleanup failure
                record_cleanup_error(exc)
        if recovery_fd is not None:
            owned_recovery_fd = recovery_fd
            recovery_fd = None
            try:
                os.close(owned_recovery_fd)
            except BaseException as exc:  # noqa: BLE001 - preserve the first cleanup failure
                record_cleanup_error(exc)
        if current_dir_fd is not None:
            owned_dir_fd = current_dir_fd
            current_dir_fd = None
            try:
                os.close(owned_dir_fd)
            except BaseException as exc:  # noqa: BLE001 - preserve the first cleanup failure
                record_cleanup_error(exc)
        if cleanup_error is not None:
            raise cleanup_error


def advanced_uri_from_vault_path(path: Path | str, *, vault_root: Path | str) -> str:
    resolved_path = Path(path).expanduser().resolve()
    resolved_root = Path(vault_root).expanduser().resolve()
    try:
        rel = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        rel = resolved_path.name
    return build_obsidian_advanced_uri(make_note_locator(rel))


__all__ = [
    "CandidateCreateResult",
    "KNOWLEDGE_WRITE_ACTION",
    "advanced_uri_from_vault_path",
    "append_note_relative",
    "candidate_note_exists_durable",
    "create_candidate_note_once",
    "default_vault_root_for_path",
    "read_note_text_with_version",
    "write_note_from_absolute",
    "write_note_relative",
]
