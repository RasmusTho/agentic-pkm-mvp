"""Bounded public-file mechanics, not a native installer or admission mechanism.

The caller owns source review, authenticated root identities and exclusion of all
other writers for the lifetime of the returned handle. Directory flocks serialize
cooperating calls to this component only; they are NOT native admission exclusion.
There is no CLI, restart/replay reader, service call, or live-success receipt.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys
import threading
from dataclasses import dataclass, field
from typing import Mapping, NoReturn
from uuid import uuid4
import weakref


@dataclass(frozen=True)
class Root:
    """An already-authenticated absolute directory identity supplied by the caller."""

    path: str
    device: int
    inode: int
    uid: int
    gid: int
    mode: int


@dataclass(frozen=True)
class Change:
    root: str
    path: str
    before_sha256: str | None
    before_mode: int | None
    after_sha256: str
    mode: int


class InstallationRefused(Exception):
    """No success is implied, including when owned material is retained."""

    def __init__(self, reason: str, installation: Installation | None = None):
        super().__init__(reason)
        self.reason = reason
        self.installation = installation


@dataclass
class _Directory:
    fd: int
    info: os.stat_result
    parent: int | None
    name: str


@dataclass
class _File:
    fd: int
    info: os.stat_result
    data: bytes


@dataclass
class _Target:
    change: Change
    parent: int
    before: _File | None
    after: bytes
    uid: int
    gid: int
    written: _File | None = None
    applied: bool = False


@dataclass
class Installation:
    """Invocation-local ownership; never reconstruct this handle from disk.

    close() releases descriptors/coordination, not backups. Compensation is one-shot
    and available only while this invocation still holds its identities.
    """

    bundle_path: str
    state: str = "preparing"
    compensation: list[tuple[str, str]] = field(default_factory=list)
    compensation_attempted: bool = False
    compensation_complete: bool | None = None
    _directories: list[_Directory] = field(default_factory=list, repr=False)
    _targets: list[_Target] = field(default_factory=list, repr=False)
    _backup_files: dict[str, _File] = field(default_factory=dict, repr=False)
    _fds: list[int] = field(default_factory=list, repr=False)
    _bundle: int | None = field(default=None, repr=False)
    _backup_parent: int | None = field(default=None, repr=False)
    _bundle_name: str = field(default="", repr=False)
    _owner_pid: int = field(default_factory=os.getpid, init=False, repr=False)

    def _require_owner_process(self) -> None:
        if self._owner_pid != os.getpid():
            _refuse("installation_owner_process_refused")
        if any(os.get_inheritable(descriptor) for descriptor in self._fds):
            _refuse("installation_descriptor_refused")

    def close(self) -> None:
        self._require_owner_process()
        for fd in reversed(self._fds):
            os.close(fd)
        self._fds.clear()
        _LIVE_INSTALLATIONS.pop(id(self), None)
        self.state = "closed"

    def __enter__(self) -> Installation:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_LIVE_INSTALLATIONS: weakref.WeakValueDictionary[int, Installation] = weakref.WeakValueDictionary()

# The generic public-file mechanic keeps its historic module-call ceiling. The
# trusted full-source path has a separate bound derived from two independently
# bounded source inventories (old and candidate), plus its fixed contract and
# launcher entries.
_MAX_LEGACY_MANIFEST_CHANGES = 192
_MAX_SOURCE_FILES = 4096
_MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_MANIFEST_CHANGES = 2 * _MAX_SOURCE_FILES + 2
# Reserve a conservative sum of transient descriptors in the fixed source
# lifecycle: one retained runtime FD, all seven parent-side descriptors that
# subprocess.Popen may hold while starting a DEV/TEST service command with
# DEVNULL stdin and captured stdout/stderr, and one backup-directory listing.
# The listing and subprocess do not overlap in the current serial lifecycle;
# summing them avoids depending on that sequencing for the admission bound.
_SOURCE_DESCRIPTOR_TRANSIENT_RESERVE = 9


def _refuse(reason: str) -> NoReturn:
    raise InstallationRefused(reason)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def _version(info: os.stat_result) -> tuple[int, ...]:
    return (*_identity(info), info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path(value: str, *, absolute: bool = False) -> tuple[str, ...]:
    if (not isinstance(value, str) or not value or "\x00" in value or "\\" in value
            or value.startswith("/") != absolute or value == "/"):
        _refuse("path_refused")
    parts = value.split("/")[1:] if absolute else value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _refuse("path_refused")
    return tuple(parts)


def _validate_manifest(roots: Mapping[str, Root], changes: tuple[Change, ...],
                       payloads: Mapping[tuple[str, str], bytes], backup: Root, *,
                       change_limit: int, total_payload_limit: int | None = None) -> None:
    if any(not isinstance(c, Change) or not isinstance(c.root, str)
           or not isinstance(c.path, str) for c in changes):
        _refuse("manifest_refused")
    if not changes or len(changes) > change_limit or set(roots) != {c.root for c in changes}:
        _refuse("manifest_refused")
    if not set(roots) <= {"application", "control", "launcher"}:
        _refuse("manifest_refused")
    keys = [(c.root, c.path) for c in changes]
    if len(set(keys)) != len(keys) or set(payloads) != set(keys):
        _refuse("manifest_refused")
    paths = []
    for root in (*roots.values(), backup):
        if not isinstance(root, Root) or any(type(value) is not int for value in (
                root.device, root.inode, root.uid, root.gid, root.mode)):
            _refuse("root_refused")
        _path(root.path, absolute=True)
        if root.mode not in {0o700, 0o755} or root.uid != os.geteuid():
            _refuse("root_refused")
        paths.append(PurePosixPath(root.path))
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(paths) for b in paths[i + 1:]):
        _refuse("root_alias_refused")
    total_payload_bytes = 0
    for change in changes:
        parts = _path(change.path)
        source_path = (len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9_]+\.py", parts[-1])
                       and all(re.fullmatch(r"[A-Za-z0-9_]+", p) for p in parts[:-1]))
        allowed = (
            (source_path and (parts[0] == "app" or
                              (change.root == "application" and parts[0] == "scripts")))
            if change.root in {"application", "control"} else
            change.path == "yggdrasil-bws-deploy"
        )
        if change.root == "application" and change.path == "config/secrets/host_secret_contract.json":
            allowed = True
        mode_ok = (
            change.mode == 0o755 if change.root == "launcher" else
            change.mode in {0o644, 0o755} if source_path else
            change.mode == 0o644
        )
        before_ok = ((change.before_sha256 is None and change.before_mode is None)
                     or (isinstance(change.before_sha256, str)
                         and re.fullmatch(r"[0-9a-f]{64}", change.before_sha256)
                         and type(change.before_mode) is int
                         and change.before_mode in {0o600, 0o644, 0o700, 0o755}))
        data = payloads[(change.root, change.path)]
        if (not allowed or type(change.mode) is not int or not mode_ok or not before_ok
                or not isinstance(change.after_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", change.after_sha256) is None
                or not isinstance(data, bytes) or len(data) > _MAX_SOURCE_FILE_BYTES
                or _hash(data) != change.after_sha256):
            _refuse("manifest_refused")
        total_payload_bytes += len(data)
        if total_payload_limit is not None and total_payload_bytes > total_payload_limit:
            _refuse("manifest_refused")


def _manifest(roots: Mapping[str, Root], changes: tuple[Change, ...],
              payloads: Mapping[tuple[str, str], bytes], backup: Root) -> None:
    """Validate the unchanged generic/legacy manifest contract."""
    _validate_manifest(roots, changes, payloads, backup,
                       change_limit=_MAX_LEGACY_MANIFEST_CHANGES)


def _source_manifest(roots: Mapping[str, Root], changes: tuple[Change, ...],
                     payloads: Mapping[tuple[str, str], bytes], backup: Root) -> None:
    """Validate a full-source manifest selected only by its production caller."""
    _validate_manifest(roots, changes, payloads, backup,
                       change_limit=_MAX_SOURCE_MANIFEST_CHANGES,
                       total_payload_limit=_MAX_TOTAL_SOURCE_BYTES)


def _source_descriptor_capacity_snapshot() -> tuple[int, int, int] | None:
    """Return this process's FD count and finite soft/hard NOFILE limits."""
    try:
        import resource

        soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
        if (type(soft_limit) is not int or type(hard_limit) is not int
                or not 0 < soft_limit <= hard_limit
                or soft_limit == resource.RLIM_INFINITY or hard_limit == resource.RLIM_INFINITY):
            return None
        entries = os.listdir("/dev/fd")
        if any(not entry.isdecimal() for entry in entries):
            return None
        # The directory enumeration may or may not expose its own FD on the
        # current platform, so count one extra descriptor conservatively.
        return len(entries) + 1, soft_limit, hard_limit
    except (ImportError, OSError, AttributeError, ValueError):
        return None


def _source_descriptor_accounting() -> tuple[int, int, int]:
    snapshot = _source_descriptor_capacity_snapshot()
    if (not isinstance(snapshot, tuple) or len(snapshot) != 3
            or type(snapshot[0]) is not int or snapshot[0] < 0
            or type(snapshot[1]) is not int or type(snapshot[2]) is not int
            or not 0 < snapshot[1] <= snapshot[2]):
        _refuse("descriptor_capacity_unknown")
    return snapshot


def _source_descriptor_process_eligible() -> bool:
    """Only the exact, single-threaded launcher CLI may change its own soft cap.

    The launcher establishes this marker only in its verified __main__ source-RPC
    branch. Neither imported RPC callers, the shared server, nor request/env data
    can opt in. The kernel task census also rejects non-Python native threads.
    """
    pid = os.getpid()
    try:
        return (
            getattr(sys, "_yggdrasil_bws_source_rpc_process", None) == pid
            and threading.current_thread() is threading.main_thread()
            and threading.active_count() == 1
            and os.listdir("/proc/self/task") == [str(pid)]
        )
    except OSError:
        return False


class _SourceDescriptorEnvelope:
    """One same-process admission; the caller closes owned resources before restore."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._original: tuple[int, int] | None = None
        self._admitted = False

    def admit(self, roots: Mapping[str, Root], changes: tuple[Change, ...], backup_root: Root,
              source_inventory_fd_peak: int) -> None:
        if self._pid != os.getpid() or self._admitted or not _source_descriptor_process_eligible():
            _refuse("descriptor_capacity_ineligible")
        open_descriptors, soft_limit, hard_limit = _source_descriptor_accounting()
        required = open_descriptors + _source_descriptor_peak(
            roots, changes, backup_root, source_inventory_fd_peak,
        )
        if required > hard_limit:
            _refuse("descriptor_capacity_insufficient")
        if required > soft_limit:
            import resource

            # Preserve before attempting the syscall: failure/readback ambiguity
            # still requires restoration or termination of this dedicated CLI.
            self._original = (soft_limit, hard_limit)
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (required, hard_limit))
                if resource.getrlimit(resource.RLIMIT_NOFILE) != (required, hard_limit):
                    _refuse("descriptor_capacity_admission_refused")
            except (OSError, ValueError):
                _refuse("descriptor_capacity_admission_refused")
        # Repeat the ordinary real guard after admission; no guessed budget or
        # setter success replaces same-process accounting.
        _require_source_descriptor_capacity(roots, changes, backup_root, source_inventory_fd_peak)
        self._admitted = True

    def close(self, *, owned_resources_closed: bool) -> None:
        if self._original is None:
            return
        # This is only reachable inside the one-shot __main__ RPC. If closure or
        # restoration cannot be proved, terminate before returning to any caller
        # or running unrelated Python/atexit work with the changed envelope.
        if self._pid != os.getpid() or owned_resources_closed is not True:
            os._exit(78)
        try:
            import resource

            if resource.getrlimit(resource.RLIMIT_NOFILE)[1] != self._original[1]:
                os._exit(78)
            resource.setrlimit(resource.RLIMIT_NOFILE, self._original)
            if resource.getrlimit(resource.RLIMIT_NOFILE) != self._original:
                os._exit(78)
        except BaseException:
            os._exit(78)
        self._original = None


def _source_descriptor_peak(roots: Mapping[str, Root], changes: tuple[Change, ...],
                            backup_root: Root, source_inventory_fd_peak: int = 0, *,
                            runtime_fd_already_open: bool = False,
                            control_path_fds_already_open: int = 0) -> int:
    """Bound handles, lifecycle transients, and held-handle readers."""
    root_descriptors = sum(
        1 + len(_path(root.path, absolute=True)) for root in (*roots.values(), backup_root)
    )
    target_parent_descriptors = sum(len(_path(change.path)) - 1 for change in changes)
    existing_targets = sum(change.before_sha256 is not None for change in changes)

    # Preparation retains roots/ancestors, every target parent and prior file,
    # one backup file for each existing target, plus the bundle directory and
    # manifest. Apply retains one staged inode FD per change. Compensation can
    # add a restore inode FD and a reopened restored-target FD per prior file.
    prepared = root_descriptors + target_parent_descriptors + 2 * existing_targets + 2
    applied = prepared + len(changes)
    compensated = applied + 2 * existing_targets
    if type(source_inventory_fd_peak) is not int or source_inventory_fd_peak < 0:
        _refuse("descriptor_capacity_unknown")
    if type(runtime_fd_already_open) is not bool:
        _refuse("descriptor_capacity_unknown")
    try:
        from app.ops.bws_installation_lifecycle import (
            _control_projection_descriptor_bound, _control_path_descriptor_bound,
        )
        control_projection_fd_peak = _control_projection_descriptor_bound()
        control_path_fd_peak = _control_path_descriptor_bound()
    except Exception:
        _refuse("descriptor_capacity_unknown")
    if type(control_projection_fd_peak) is not int or control_projection_fd_peak < 0:
        _refuse("descriptor_capacity_unknown")
    if (type(control_path_fds_already_open) is not int
            or not 0 <= control_path_fds_already_open <= control_path_fd_peak
            or (control_path_fds_already_open and not runtime_fd_already_open)):
        _refuse("descriptor_capacity_unknown")
    runtime_fd = 0 if runtime_fd_already_open else 1
    lifecycle_transients = _SOURCE_DESCRIPTOR_TRANSIENT_RESERVE - runtime_fd
    handle_peak = max(prepared, applied, compensated)
    return max(
        handle_peak + lifecycle_transients + control_path_fd_peak,
        handle_peak + runtime_fd + source_inventory_fd_peak + control_path_fd_peak,
        # FixedBwsService._config retains this bounded source-only projection
        # while the prepared handle and runtime reader remain held.
        handle_peak + runtime_fd + control_projection_fd_peak,
    ) - control_path_fds_already_open


def _require_source_descriptor_capacity(roots: Mapping[str, Root], changes: tuple[Change, ...],
                                        backup_root: Root, source_inventory_fd_peak: int = 0, *,
                                        runtime_fd_already_open: bool = False,
                                        control_path_fds_already_open: int = 0) -> None:
    open_descriptors, soft_limit, _hard_limit = _source_descriptor_accounting()
    required_peak = _source_descriptor_peak(
        roots, changes, backup_root, source_inventory_fd_peak,
        runtime_fd_already_open=runtime_fd_already_open,
        control_path_fds_already_open=control_path_fds_already_open,
    )
    if open_descriptors + required_peak > soft_limit:
        _refuse("descriptor_capacity_insufficient")


def _directory(handle: Installation, name: str, parent: int | None,
               uid: int, *, ancestors: bool = False) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    handle._fds.append(fd)
    info = os.fstat(fd)
    # Sticky shared ancestors (e.g. /tmp) do not authorize mutable target roots.
    sticky = ancestors and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
    if info.st_uid not in ({0, uid} if ancestors else {uid}) or (info.st_mode & 0o022 and not sticky):
        _refuse("directory_refused")
    if not ancestors and stat.S_IMODE(info.st_mode) not in {0o700, 0o755}:
        _refuse("directory_refused")
    handle._directories.append(_Directory(fd, info, parent, name))
    return fd


def _root(handle: Installation, root: Root) -> int:
    fd = _directory(handle, "/", None, root.uid, ancestors=True)
    for part in _path(root.path, absolute=True):
        fd = _directory(handle, part, fd, root.uid, ancestors=True)
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
            root.device, root.inode, root.uid, root.gid, root.mode):
        _refuse("root_refused")
    return fd


def _tree(handle: Installation) -> None:
    for directory in handle._directories:
        current = os.stat(directory.name, dir_fd=directory.parent, follow_symlinks=False)
        if _identity(current) != _identity(directory.info) or _identity(os.fstat(directory.fd)) != _identity(directory.info):
            _refuse("ancestor_drift")


def _read(fd: int) -> bytes:
    info = os.fstat(fd)
    if info.st_size > 8 * 1024 * 1024:
        _refuse("file_refused")
    data = os.pread(fd, info.st_size + 1, 0)
    if len(data) != info.st_size or _version(os.fstat(fd)) != _version(info):
        _refuse("file_drift")
    return data


def _file(handle: Installation, parent: int, name: str, uid: int, gid: int, mode: int) -> _File:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    handle._fds.append(fd)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != uid
            or info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode):
        _refuse("file_refused")
    result = _File(fd, info, _read(fd))
    _same(parent, name, result)
    return result


def _same(parent: int, name: str, expected: _File | None) -> None:
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if expected is None:
            return
        _refuse("file_missing")
    if expected is None or _version(info) != _version(expected.info):
        _refuse("file_drift")
    if _version(os.fstat(expected.fd)) != _version(expected.info) or _read(expected.fd) != expected.data:
        _refuse("file_drift")


def _create(handle: Installation, parent: int, name: str, data: bytes, mode: int,
            *, preserve: bool = True) -> _File:
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    handle._fds.append(fd)
    try:
        offset = 0
        while offset < len(data):
            count = os.write(fd, data[offset:])
            if count <= 0:
                _refuse("short_write")
            offset += count
        os.fchmod(fd, mode)
        os.fsync(fd)
        result = _File(fd, os.fstat(fd), data)
        if (not stat.S_ISREG(result.info.st_mode) or result.info.st_nlink != 1
                or result.info.st_uid != os.geteuid()):
            _refuse("file_refused")
        _same(parent, name, result)
        return result
    except (OSError, InstallationRefused):
        if not preserve and _exists(parent, name):
            if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(os.fstat(fd)):
                _refuse("temporary_drift")
            os.unlink(name, dir_fd=parent)
        raise


def _backup_valid(handle: Installation) -> None:
    _tree(handle)
    if handle._bundle is None or set(os.listdir(handle._bundle)) != set(handle._backup_files):
        _refuse("backup_refused")
    for name, saved in handle._backup_files.items():
        _same(handle._bundle, name, saved)


def _backup(handle: Installation, parent: int, name: str) -> None:
    # Exclusive final-name creation means no rename can replace/adopt a foreign
    # bundle. An incomplete bundle stays at this name and permanently refuses reuse.
    os.mkdir(name, 0o700, dir_fd=parent)
    bundle = _directory(handle, name, parent, os.geteuid())
    handle._bundle = bundle
    handle._backup_parent = parent
    handle._bundle_name = name
    if stat.S_IMODE(os.fstat(bundle).st_mode) != 0o700:
        _refuse("backup_refused")
    rows = []
    for index, target in enumerate(handle._targets):
        saved_name = f"{index:04d}.before"
        before = target.before
        if before is not None:
            handle._backup_files[saved_name] = _create(handle, bundle, saved_name, before.data, 0o600)
        rows.append({"root": target.change.root, "path": target.change.path,
                     "before": None if before is None else {
                         "file": saved_name, "sha256": _hash(before.data),
                         "mode": stat.S_IMODE(before.info.st_mode)},
                     "after_sha256": target.change.after_sha256, "mode": target.change.mode})
    os.fsync(bundle)
    raw = (json.dumps(rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    handle._backup_files["manifest.json"] = _create(handle, bundle, "manifest.json", raw, 0o600)
    os.fsync(bundle)
    os.fsync(parent)
    _backup_valid(handle)


def _replace(handle: Installation, target: _Target, data: bytes, mode: int,
             expected: _File | None) -> _File:
    name = PurePosixPath(target.change.path).name
    temporary = ".bws-install-" + uuid4().hex
    staged = _create(handle, target.parent, temporary, data, mode, preserve=False)
    try:
        if staged.info.st_uid != target.uid or staged.info.st_gid != target.gid:
            _refuse("file_refused")
        _tree(handle)
        _same(target.parent, name, expected)
        if expected is None:
            # Absence is not ownership: link publishes without replacing a newcomer.
            os.link(temporary, name, src_dir_fd=target.parent, dst_dir_fd=target.parent,
                    follow_symlinks=False)
            os.unlink(temporary, dir_fd=target.parent)
        else:
            os.replace(temporary, name, src_dir_fd=target.parent, dst_dir_fd=target.parent)
    finally:
        # Even an exception after rename cannot erase ownership of the held inode.
        current = os.stat(name, dir_fd=target.parent, follow_symlinks=False) if _exists(target.parent, name) else None
        if current is not None and _identity(current) == _identity(os.fstat(staged.fd)):
            staged.info = os.fstat(staged.fd)
            target.written = staged
        if _exists(target.parent, temporary):
            current_temporary = os.stat(temporary, dir_fd=target.parent, follow_symlinks=False)
            if _identity(current_temporary) != _identity(os.fstat(staged.fd)):
                _refuse("temporary_drift")
            os.unlink(temporary, dir_fd=target.parent)
            if target.written is staged:
                staged.info = os.fstat(staged.fd)
    os.fsync(target.parent)
    _same(target.parent, name, staged)
    return staged


def _exists(parent: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _compensate(handle: Installation) -> bool:
    try:
        _backup_valid(handle)
    except (OSError, InstallationRefused):
        handle.compensation.extend((t.change.path, "refused") for t in handle._targets if t.written is not None)
        return False
    complete = True
    for index in range(len(handle._targets) - 1, -1, -1):
        target = handle._targets[index]
        outcome = "refused"
        try:
            _backup_valid(handle)
            name = PurePosixPath(target.change.path).name
            if target.written is None:
                # Already-matching and not-yet-written files are still part of
                # the recovery proof. Do not start the old service if any one
                # of these targets drifted after its preflight snapshot.
                _same(target.parent, name, target.before)
                outcome = "unchanged"
            else:
                _same(target.parent, name, target.written)
                if target.before is None:
                    os.unlink(name, dir_fd=target.parent)
                    os.fsync(target.parent)
                    _same(target.parent, name, None)
                    outcome = "removed"
                else:
                    saved = handle._backup_files[f"{index:04d}.before"]
                    _replace(handle, target, saved.data,
                             stat.S_IMODE(target.before.info.st_mode), target.written)
                    restored = _file(handle, target.parent, name, target.uid, target.gid,
                                     stat.S_IMODE(target.before.info.st_mode))
                    if restored.data != target.before.data:
                        _refuse("file_drift")
                    outcome = "restored"
        except (OSError, InstallationRefused):
            pass
        if target.written is not None or outcome == "refused":
            handle.compensation.append((target.change.path, outcome))
        if outcome == "refused":
            complete = False
    return complete


def install_public_files(*, roots: Mapping[str, Root], changes: tuple[Change, ...],
                         payloads: Mapping[tuple[str, str], bytes], backup_root: Root,
                         bundle_name: str) -> Installation:
    """Back up and install this exact manifest once; compensate owned partial writes.

    On refusal the exception retains a handle when allocated. Close it after
    inspection. Neither a failure nor close removes any backup or authorizes replay.
    """
    return apply_public_files(prepare_public_files(
        roots=roots, changes=changes, payloads=payloads,
        backup_root=backup_root, bundle_name=bundle_name,
    ))


def _prepare_public_files(*, roots: Mapping[str, Root], changes: tuple[Change, ...],
                          payloads: Mapping[tuple[str, str], bytes], backup_root: Root,
                          bundle_name: str, full_source_manifest: bool,
                          source_inventory_fd_peak: int = 0,
                          runtime_fd_already_open: bool = False,
                          control_path_fds_already_open: int = 0) -> Installation:
    """Validate and durably back up a finite manifest without replacing targets.

    The returned handle retains the exact root, target, backup and flock identities
    required by ``apply_public_files`` and compensation. Close it only after the
    caller's surrounding operation reaches its terminal decision. A failed
    preparation preserves any allocated backup bundle and never authorizes replay.
    """
    roots, changes, payloads = dict(roots), tuple(changes), dict(payloads)
    validate = _source_manifest if full_source_manifest else _manifest
    validate(roots, changes, payloads, backup_root)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", bundle_name) is None:
        _refuse("bundle_name_refused")
    if full_source_manifest:
        _require_source_descriptor_capacity(
            roots, changes, backup_root, source_inventory_fd_peak,
            runtime_fd_already_open=runtime_fd_already_open,
        control_path_fds_already_open=control_path_fds_already_open,
        )
    handle = Installation(backup_root.path + "/" + bundle_name)
    try:
        opened = {name: _root(handle, root) for name, root in roots.items()}
        backup_fd = _root(handle, backup_root)
        all_roots = [*opened.values(), backup_fd]
        if len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in all_roots}) != len(all_roots):
            _refuse("root_alias_refused")
        for fd in sorted(all_roots, key=lambda item: (os.fstat(item).st_dev, os.fstat(item).st_ino)):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _exists(backup_fd, bundle_name):
            _refuse("bundle_exists")
        for change in changes:
            parent = opened[change.root]
            root = roots[change.root]
            parts = _path(change.path)
            for part in parts[:-1]:
                parent = _directory(handle, part, parent, root.uid)
            before = None
            if change.before_sha256 is not None:
                before = _file(handle, parent, parts[-1], root.uid, root.gid, change.before_mode)  # type: ignore[arg-type]
                if _hash(before.data) != change.before_sha256:
                    _refuse("before_mismatch")
            _same(parent, parts[-1], before)
            handle._targets.append(_Target(change, parent, before, payloads[(change.root, change.path)], root.uid, root.gid))
        existing_ids = [(t.before.info.st_dev, t.before.info.st_ino)
                        for t in handle._targets if t.before is not None]
        if len(existing_ids) != len(set(existing_ids)):
            _refuse("file_alias_refused")
        _tree(handle)
        _backup(handle, backup_fd, bundle_name)
        for target in handle._targets:
            _same(target.parent, PurePosixPath(target.change.path).name, target.before)
        handle.state = "prepared"
        _LIVE_INSTALLATIONS[id(handle)] = handle
        return handle
    except (OSError, InstallationRefused) as exc:
        handle.state = "refused"
        reason = exc.reason if isinstance(exc, InstallationRefused) else "filesystem_refused"
        raise InstallationRefused(reason, handle) from None


def prepare_public_files(*, roots: Mapping[str, Root], changes: tuple[Change, ...],
                         payloads: Mapping[tuple[str, str], bytes], backup_root: Root,
                         bundle_name: str) -> Installation:
    """Prepare the existing bounded generic/legacy public-file contract."""
    return _prepare_public_files(roots=roots, changes=changes, payloads=payloads,
                                  backup_root=backup_root, bundle_name=bundle_name,
                                  full_source_manifest=False)


def _prepare_full_source_files(*, roots: Mapping[str, Root], changes: tuple[Change, ...],
                               payloads: Mapping[tuple[str, str], bytes], backup_root: Root,
                               bundle_name: str, source_inventory_fd_peak: int = 0,
                               runtime_fd_already_open: bool = False,
                          control_path_fds_already_open: int = 0) -> Installation:
    """Prepare the internal full-source path with its derived source manifest budget."""
    return _prepare_public_files(roots=roots, changes=changes, payloads=payloads,
                                  backup_root=backup_root, bundle_name=bundle_name,
                                  full_source_manifest=True,
                                  source_inventory_fd_peak=source_inventory_fd_peak,
                                  runtime_fd_already_open=runtime_fd_already_open,
                                  control_path_fds_already_open=control_path_fds_already_open)


def apply_public_files(
    handle: Installation, *, target_keys: tuple[tuple[str, str], ...] | None = None,
) -> Installation:
    """Install selected targets through the exact still-open prepared handle.

    A caller may apply disjoint subsets in order while retaining the same
    backup/compensation authority. Every target remains bound to its original
    identity; a later subset refuses if an earlier or not-yet-applied target
    drifted.
    """
    if (not isinstance(handle, Installation) or handle.state not in {"prepared", "partially_installed"}
            or _LIVE_INSTALLATIONS.get(id(handle)) is not handle):
        raise InstallationRefused(
            "installation_state_refused",
            handle if isinstance(handle, Installation) else None,
        )
    handle._require_owner_process()
    try:
        all_keys = {(target.change.root, target.change.path) for target in handle._targets}
        if target_keys is None:
            selected_keys = all_keys
        else:
            selected_keys = set(target_keys)
            if (not target_keys or len(selected_keys) != len(target_keys)
                    or not selected_keys <= all_keys):
                _refuse("target_selection_refused")
        _backup_valid(handle)
        for target in handle._targets:
            expected = target.written if target.applied and target.written is not None else target.before
            _same(target.parent, PurePosixPath(target.change.path).name, expected)
        handle.state = "installing" if selected_keys == all_keys else "partially_installing"
        for target in handle._targets:
            key = (target.change.root, target.change.path)
            if key not in selected_keys or target.applied:
                continue
            _backup_valid(handle)
            _same(target.parent, PurePosixPath(target.change.path).name, target.before)
            if (target.before is not None and target.before.data == target.after
                    and stat.S_IMODE(target.before.info.st_mode) == target.change.mode):
                target.applied = True
                continue
            _replace(handle, target, target.after, target.change.mode, target.before)
            target.applied = True
        _backup_valid(handle)
        for target in handle._targets:
            _same(target.parent, PurePosixPath(target.change.path).name,
                  target.written if target.applied and target.written is not None else target.before)
        handle.state = ("installed" if all(target.applied for target in handle._targets)
                        else "partially_installed")
        return handle
    except (OSError, InstallationRefused) as exc:
        if handle.state in {"installing", "partially_installing"}:
            handle.compensation_attempted = True
            handle.compensation_complete = _compensate(handle)
        handle.state = "refused"
        reason = exc.reason if isinstance(exc, InstallationRefused) else "filesystem_refused"
        raise InstallationRefused(reason, handle) from None


def compensate_public_files(handle: Installation) -> tuple[tuple[str, str], ...]:
    """Verify an untouched prepared handle or restore exact installed inodes once.

    The whole backup must remain valid even when no target needed replacement.
    Per-target outcomes remain available on the handle when compensation refuses.
    """
    if (not isinstance(handle, Installation)
            or handle.state not in {"prepared", "partially_installed", "installed"}
            or _LIVE_INSTALLATIONS.get(id(handle)) is not handle):
        raise InstallationRefused("compensation_state_refused", handle)
    handle._require_owner_process()
    handle.state = "compensating"
    handle.compensation_attempted = True
    handle.compensation_complete = _compensate(handle)
    if not handle.compensation_complete:
        handle.state = "compensation_refused"
        raise InstallationRefused("compensation_refused", handle)
    handle.state = "compensated"
    return tuple(handle.compensation)
