from __future__ import annotations

import sys
import ctypes
import tempfile
import errno
import fcntl
import json
import os
import shutil
import stat
import time
import uuid
from pathlib import Path

import pytest

# Test collection from a fresh source worktree is the pytest consumer class that
# has no editable-install prerequisite. Keep this one root-level fallback;
# package consumers use the pyproject.toml editable-install declaration.
_COMPANION_APP_ROOT = Path(__file__).resolve().parent / "companion-ui" / "companion-app"
if str(_COMPANION_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPANION_APP_ROOT))


_TEMP_PREFIX = "pkm-py-"
_TEMP_LEGACY_PREFIX = "agentic-pkm-pytest-"
_TEMP_OWNER = ".agentic-pkm-pytest-owner.json"
_TEMP_FINISHED = ".agentic-pkm-pytest-finished.json"
_TEMP_CHILD_PREFIX = ".agentic-pkm-pytest-child-"
_TEMP_PARENT_LOCK = ".agentic-pkm-pytest-parent.lock"
_TEMP_RETENTION_NS = 7 * 24 * 60 * 60 * 1_000_000_000
_TEMP_SCAN_SECONDS = 5.0
_TEMP_SCAN_MAX_ENTRIES = 100_000


class _TempParentBusy(OSError):
    """A valid cooperative parent lock could not be acquired in time."""


class _DarwinStatFS(ctypes.Structure):
    # Darwin's public 64-bit struct statfs from sys/mount.h.
    _fields_ = [
        ("bsize", ctypes.c_uint32), ("iosize", ctypes.c_int32),
        ("blocks", ctypes.c_uint64), ("bfree", ctypes.c_uint64), ("bavail", ctypes.c_uint64),
        ("files", ctypes.c_uint64), ("ffree", ctypes.c_uint64), ("fsid", ctypes.c_int32 * 2),
        ("owner", ctypes.c_uint32), ("type", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("subtype", ctypes.c_uint32), ("fstype", ctypes.c_char * 16),
        ("mountpoint", ctypes.c_char * 1024), ("source", ctypes.c_char * 1024),
        ("flags_ext", ctypes.c_uint32), ("reserved", ctypes.c_uint32 * 7),
    ]


class _LinuxStatFS(ctypes.Structure):
    # Linux 64-bit struct statfs; unknown ABIs are refused below.
    _fields_ = [
        ("type", ctypes.c_long), ("bsize", ctypes.c_long), ("blocks", ctypes.c_ulong),
        ("bfree", ctypes.c_ulong), ("bavail", ctypes.c_ulong), ("files", ctypes.c_ulong),
        ("ffree", ctypes.c_ulong), ("fsid", ctypes.c_int32 * 2), ("namelen", ctypes.c_long),
        ("frsize", ctypes.c_long), ("flags", ctypes.c_long), ("spare", ctypes.c_long * 4),
    ]


def _temp_mount_identity(fd: int) -> tuple[object, ...]:
    """Identify an ownership-enforcing mount from the held directory descriptor.

    Unknown filesystems and missing mount evidence are not cleanup authority.
    This checks the OS mount, not adversarial root remounts outside our lock model.
    """
    try:
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError("unsupported mount ABI")
        if sys.platform == "darwin":
            result = _DarwinStatFS()
        elif sys.platform.startswith("linux"):
            result = _LinuxStatFS()
        else:
            raise OSError("unsupported mount platform")
        libc = ctypes.CDLL(None, use_errno=True)
        fstatfs = libc.fstatfs
        fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)
        fstatfs.restype = ctypes.c_int
        if fstatfs(fd, ctypes.byref(result)) != 0:
            raise OSError(ctypes.get_errno(), "fstatfs failed")
        if isinstance(result, _DarwinStatFS):
            # MNT_IGNORE_OWNERSHIP is not exposed by Python statvfs.f_flag.
            if (result.fstype not in {b"apfs", b"hfs"} or result.flags & 0x00200000
                    or result.flags_ext & 0x2):  # FSKit has unverified ownership semantics.
                raise OSError("unqualified mount ownership")
            return ("darwin", tuple(result.fsid), result.fstype, result.mountpoint, result.source)
        # These local Linux filesystems enforce Unix ownership. Network, FUSE,
        # and unrecognized types are intentionally not inferred to do so.
        if result.type not in {0xEF53, 0x58465342, 0x9123683E, 0x01021994, 0x794C7630}:
            raise OSError("unqualified mount ownership")
        with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as source:
            lines = source.read(4097)
        matches = [line.partition(":")[2].strip() for line in lines.splitlines()
                   if line.startswith("mnt_id:")]
        if len(lines) > 4096 or len(matches) != 1 or not matches[0].isdecimal():
            raise OSError("unavailable mount identity")
        return ("linux", result.type, tuple(result.fsid), int(matches[0]))
    except (AttributeError, OSError, ValueError, OverflowError) as exc:
        raise OSError("pytest mount ownership is not qualified") from exc


def _same_temp_mount(parent: Path, fd: int, expected: tuple[object, ...]) -> bool:
    """Compare the held parent with its current name and original mount."""
    other = None
    try:
        other = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        held, named = os.fstat(fd), os.fstat(other)
        return ((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
                and _temp_mount_identity(fd) == expected == _temp_mount_identity(other))
    except OSError:
        return False
    finally:
        if other is not None:
            os.close(other)


def _temp_tree_on_mount(root_fd: int, expected: tuple[object, ...], deadline: float) -> bool:
    """Refuse a candidate containing another or unprovable mount.

    Never follow links or open special files. A closed, exclusively locked
    cooperative namespace cannot acquire new entries during this walk.
    """
    remaining = _TEMP_SCAN_MAX_ENTRIES
    def visit(directory_fd: int) -> bool:
        nonlocal remaining
        if time.monotonic() >= deadline or _temp_mount_identity(directory_fd) != expected:
            return False
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                remaining -= 1
                if remaining < 0 or time.monotonic() >= deadline:
                    return False
                before = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode):
                    continue
                is_dir = stat.S_ISDIR(before.st_mode)
                if not is_dir and not stat.S_ISREG(before.st_mode):
                    return False
                flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
                if is_dir:
                    flags |= os.O_DIRECTORY
                child = os.open(entry.name, flags, dir_fd=directory_fd)
                try:
                    opened = os.fstat(child)
                    if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                            or _temp_mount_identity(child) != expected
                            or (is_dir and not visit(child))):
                        return False
                finally:
                    os.close(child)
        return True
    try:
        return visit(root_fd)
    except (OSError, RecursionError):
        return False


def _private_temp_parent(system_temp: Path) -> Path:
    """Create the stable private default without adopting an unsafe path."""
    parent = system_temp / ("pkm-" + str(os.geteuid()))
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = parent.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or not _qualified_temp_parent(parent)):
        raise OSError("pytest default parent is not private")
    return parent


def _qualified_temp_parent(parent: Path) -> bool:
    fd = None
    try:
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        mount = _temp_mount_identity(fd)
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700 and _same_temp_mount(parent, fd, mount))
    except OSError:
        return False
    finally:
        if fd is not None:
            os.close(fd)


def _lock_temp_parent(parent: Path, *, wait: bool) -> tuple[int, tuple[int, int]]:
    """Serialize cooperative namespace changes in one verified private parent."""
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    descriptor = None
    try:
        root = os.fstat(parent_fd)
        named = os.stat(parent, follow_symlinks=False)
        mount = _temp_mount_identity(parent_fd)
        if (root.st_uid != os.geteuid() or stat.S_IMODE(root.st_mode) != 0o700
                or (root.st_dev, root.st_ino) != (named.st_dev, named.st_ino)
                or not _same_temp_mount(parent, parent_fd, mount)):
            raise OSError("unqualified pytest parent")
        try:
            descriptor = os.open(_TEMP_PARENT_LOCK, os.O_RDWR | os.O_NONBLOCK | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                 | os.O_CLOEXEC, 0o600, dir_fd=parent_fd)
            os.fchmod(descriptor, 0o600)
        except FileExistsError:
            descriptor = os.open(_TEMP_PARENT_LOCK, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=parent_fd)
        lock = os.fstat(descriptor)
        lock_named = os.stat(_TEMP_PARENT_LOCK, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid() or lock.st_nlink != 1
                or stat.S_IMODE(lock.st_mode) != 0o600
                or (lock.st_dev, lock.st_ino) != (lock_named.st_dev, lock_named.st_ino)):
            raise OSError("unqualified pytest parent lock")
        deadline = time.monotonic() + (30.0 if wait else 0.0)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _TempParentBusy("pytest parent lock unavailable") from None
                time.sleep(0.01)
        named = os.stat(parent, follow_symlinks=False)
        lock_named = os.stat(_TEMP_PARENT_LOCK, dir_fd=parent_fd, follow_symlinks=False)
        if ((root.st_dev, root.st_ino) != (named.st_dev, named.st_ino)
                or (lock.st_dev, lock.st_ino) != (lock_named.st_dev, lock_named.st_ino)
                or not _same_temp_mount(parent, parent_fd, mount)):
            raise OSError("pytest parent identity changed")
        result = descriptor
        descriptor = None
        return result, (root.st_dev, root.st_ino)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _unique_temp_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate owner field")
        value[key] = item
    return value


def _open_temp_owner(directory: Path) -> tuple[int, dict[str, int]]:
    """Open a namespace marker without following links; malformed means unknown."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = os.open(directory, flags | os.O_DIRECTORY)
    marker_fd = None
    try:
        root_stat = os.fstat(directory_fd)
        named_stat = os.stat(directory, follow_symlinks=False)
        if ((root_stat.st_dev, root_stat.st_ino) != (named_stat.st_dev, named_stat.st_ino)
                or root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700):
            raise ValueError("unqualified namespace")
        marker_fd = os.open(_TEMP_OWNER, flags, dir_fd=directory_fd)
        info = os.fstat(marker_fd)
        named = os.stat(_TEMP_OWNER, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not 0 < info.st_size <= 1024):
            raise ValueError("unqualified marker")
        raw = os.read(marker_fd, 1025)
        after = os.fstat(marker_fd)
        if (len(raw) != info.st_size or info.st_mtime_ns != after.st_mtime_ns
                or (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino)):
            raise ValueError("marker changed while reading")
        value = json.loads(raw, object_pairs_hook=_unique_temp_fields)
        if (type(value) is not dict or set(value) != {"version", "pid", "created_ns", "device", "inode"}
                or type(value["version"]) is not int or value["version"] != 1
                or any(type(value[key]) is not int for key in ("pid", "created_ns", "device", "inode"))
                or not 0 < value["pid"] < 2**31 or value["created_ns"] <= 0
                or (value["device"], value["inode"]) != (root_stat.st_dev, root_stat.st_ino)):
            raise ValueError("unqualified owner")
        result = marker_fd
        marker_fd = None
        return result, value
    finally:
        os.close(directory_fd)
        if marker_fd is not None:
            os.close(marker_fd)


def _open_temp_lifetime(directory: Path) -> tuple[int | None, tuple[int, int]]:
    """Pin a parent's marker inode without sampling its mutable timestamp."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(directory, flags | os.O_DIRECTORY)
    marker_fd = None
    try:
        root = os.fstat(root_fd)
        named_root = os.stat(directory, follow_symlinks=False)
        if (root.st_dev, root.st_ino) != (named_root.st_dev, named_root.st_ino):
            raise OSError("unqualified pytest ancestor")
        try:
            marker_fd = os.open(_TEMP_OWNER, flags, dir_fd=root_fd)
        except FileNotFoundError:
            # A genuinely unmarked legacy root is never eligible for cleanup.
            named_root = os.stat(directory, follow_symlinks=False)
            if (root.st_dev, root.st_ino) != (named_root.st_dev, named_root.st_ino):
                raise OSError("pytest ancestor changed") from None
            return None, (root.st_dev, root.st_ino)
        if root.st_uid != os.geteuid() or stat.S_IMODE(root.st_mode) != 0o700:
            raise OSError("unqualified pytest ancestor")
        marker = os.fstat(marker_fd)
        named_marker = os.stat(_TEMP_OWNER, dir_fd=root_fd, follow_symlinks=False)
        if (not stat.S_ISREG(marker.st_mode) or marker.st_uid != os.geteuid()
                or stat.S_IMODE(marker.st_mode) != 0o600 or marker.st_nlink != 1
                or (marker.st_dev, marker.st_ino) != (named_marker.st_dev, named_marker.st_ino)):
            raise OSError("unqualified pytest ancestor marker")
        result = marker_fd
        marker_fd = None
        return result, (root.st_dev, root.st_ino)
    finally:
        if marker_fd is not None:
            os.close(marker_fd)
        os.close(root_fd)


def _temp_parent_locks(parent: Path) -> list[tuple[int, int, str]]:
    """Keep every marked enclosing pytest namespace alive for this run."""
    held: list[tuple[int, int, str]] = []
    try:
        for directory in (parent, *parent.parents):
            if not directory.name.startswith((_TEMP_PREFIX, _TEMP_LEGACY_PREFIX)):
                continue
            ancestor_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                try:
                    mount = _temp_mount_identity(ancestor_fd)
                except OSError:
                    # Ownership on this mount is unknown: do not treat its
                    # marker as authority or update its lifetime metadata.
                    continue
            finally:
                os.close(ancestor_fd)
            descriptor, identity = _open_temp_lifetime(directory)
            if descriptor is None:
                continue
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                # A cleaner could have renamed the root between open and lock.
                named = directory.stat(follow_symlinks=False)
                marker_info = os.fstat(descriptor)
                marker_named = (directory / _TEMP_OWNER).stat(follow_symlinks=False)
                if ((marker_info.st_dev, marker_info.st_ino) != (marker_named.st_dev, marker_named.st_ino)
                        or not stat.S_ISDIR(named.st_mode)
                        or (named.st_dev, named.st_ino) != identity):
                    raise OSError("pytest parent namespace changed")
                root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    opened = os.fstat(root_fd)
                    if ((opened.st_dev, opened.st_ino) != identity
                            or not _same_temp_mount(directory, root_fd, mount)):
                        raise OSError("pytest parent namespace changed")
                    child_name = _TEMP_CHILD_PREFIX + uuid.uuid4().hex
                    child_fd = os.open(child_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                       | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
                    try:
                        os.fchmod(child_fd, 0o600)
                        os.write(child_fd, b"nested pytest pending\n")
                        os.fsync(child_fd)
                    finally:
                        os.close(child_fd)
                    os.fsync(root_fd)
                    held.append((descriptor, root_fd, child_name))
                except BaseException:
                    os.close(root_fd)
                    raise
            except BaseException:
                os.close(descriptor)
                raise
        return held
    except BaseException:
        for descriptor, root_fd, _ in held:
            os.close(root_fd)
            os.close(descriptor)
        raise


def _finished_temp_root(directory: Path, owner: dict[str, int], cutoff: int) -> bool:
    """Require a complete old terminal marker and no uncertain child runs."""
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        root = os.fstat(root_fd)
        if (root.st_dev, root.st_ino) != (owner["device"], owner["inode"]):
            return False
        with os.scandir(root_fd) as entries:
            if any(entry.name.startswith(_TEMP_CHILD_PREFIX) for entry in entries):
                return False
        descriptor = os.open(_TEMP_FINISHED, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=root_fd)
        try:
            info = os.fstat(descriptor)
            named = os.stat(_TEMP_FINISHED, dir_fd=root_fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or not 0 < info.st_size <= 1024 or info.st_mtime_ns > cutoff):
                return False
            raw = os.read(descriptor, 1025)
            after = os.fstat(descriptor)
            if len(raw) != info.st_size or after.st_mtime_ns != info.st_mtime_ns:
                return False
            finished = json.loads(raw, object_pairs_hook=_unique_temp_fields)
            return (type(finished) is dict
                    and set(finished) == {"version", "pid", "device", "inode", "finished_ns"}
                    and type(finished["version"]) is int and finished["version"] == 1
                    and all(type(finished[key]) is int for key in ("pid", "device", "inode", "finished_ns"))
                    and all(finished[key] == owner[key] for key in ("pid", "device", "inode"))
                    and owner["created_ns"] <= finished["finished_ns"] <= cutoff)
        finally:
            os.close(descriptor)
    finally:
        os.close(root_fd)


def _prune_expired_temp_roots(parent: Path, *, now_ns: int | None = None) -> None:
    """Reclaim only old, marked, unlocked, dead-owner direct children."""
    if not shutil.rmtree.avoids_symlink_attacks or not _qualified_temp_parent(parent):
        return
    deadline = time.monotonic() + _TEMP_SCAN_SECONDS
    now = time.time_ns() if now_ns is None else now_ns
    cutoff = now - _TEMP_RETENTION_NS
    try:
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return
    try:
        try:
            mount = _temp_mount_identity(parent_fd)
        except OSError:
            return
        if not _same_temp_mount(parent, parent_fd, mount):
            return
        try:
            with os.scandir(parent_fd) as entries:
                names = []
                for index, entry in enumerate(entries):
                    if index >= _TEMP_SCAN_MAX_ENTRIES or time.monotonic() >= deadline:
                        return
                    if entry.name.startswith(_TEMP_PREFIX):
                        names.append(entry.name)
        except OSError:
            return
        for name in names:
            if time.monotonic() >= deadline:
                return
            descriptor = None
            quarantine = None
            quarantine_identity = None
            parent_lock = None
            try:
                path = parent / name
                descriptor, owner = _open_temp_owner(path)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                marker = os.fstat(descriptor)
                check_fd, rechecked = _open_temp_owner(path)
                try:
                    check_info = os.fstat(check_fd)
                    if ((marker.st_dev, marker.st_ino) != (check_info.st_dev, check_info.st_ino)
                            or rechecked != owner):
                        continue
                finally:
                    os.close(check_fd)
                root = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if ((root.st_dev, root.st_ino) != (owner["device"], owner["inode"])
                        or owner["created_ns"] > cutoff or marker.st_mtime_ns > cutoff
                        or root.st_mtime_ns > cutoff or not _finished_temp_root(path, owner, cutoff)):
                    continue
                try:
                    os.kill(owner["pid"], 0)
                except OSError as exc:
                    if exc.errno != errno.ESRCH:
                        continue
                else:
                    continue
                if not _same_temp_mount(parent, parent_fd, mount):
                    return
                candidate_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                       dir_fd=parent_fd)
                try:
                    candidate = os.fstat(candidate_fd)
                    if ((candidate.st_dev, candidate.st_ino) != (owner["device"], owner["inode"])
                            or not _temp_tree_on_mount(candidate_fd, mount, deadline)):
                        continue
                finally:
                    os.close(candidate_fd)
                # Rename into a private directory first. A late nested pytest
                # cannot enter the original pathname after the exclusive lock.
                quarantine = Path(tempfile.mkdtemp(prefix=".pytest-prune-", dir=parent))
                quarantine_fd = os.open(quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    quarantine_info = os.fstat(quarantine_fd)
                    quarantine_identity = (quarantine_info.st_dev, quarantine_info.st_ino)
                    parent_lock, identity = _lock_temp_parent(parent, wait=False)
                    parent_info = os.fstat(parent_fd)
                    named_quarantine = os.stat(quarantine.name, dir_fd=parent_fd, follow_symlinks=False)
                    final_root = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    final_fd, final_owner = _open_temp_owner(path)
                    try:
                        final_marker = os.fstat(final_fd)
                    finally:
                        os.close(final_fd)
                    if ((parent_info.st_dev, parent_info.st_ino) != identity
                            or (named_quarantine.st_dev, named_quarantine.st_ino) != quarantine_identity
                            or root.st_dev != parent_info.st_dev
                            or (final_root.st_dev, final_root.st_ino) != (owner["device"], owner["inode"])
                            or (final_marker.st_dev, final_marker.st_ino) != (marker.st_dev, marker.st_ino)
                            or final_owner != owner
                            or _temp_mount_identity(quarantine_fd) != mount
                            or not _same_temp_mount(parent, parent_fd, mount)
                            or time.monotonic() >= deadline):
                        continue
                    os.rename(name, "owned", src_dir_fd=parent_fd, dst_dir_fd=quarantine_fd)
                    moved = os.stat("owned", dir_fd=quarantine_fd, follow_symlinks=False)
                    if (moved.st_dev, moved.st_ino) != (owner["device"], owner["inode"]):
                        continue
                    # Other cooperative runs need the parent only for the
                    # namespace move, not for potentially expensive deletion.
                    os.close(parent_lock)
                    parent_lock = None
                    if (_temp_mount_identity(quarantine_fd) == mount
                            and _same_temp_mount(parent, parent_fd, mount)):
                        shutil.rmtree("owned", dir_fd=quarantine_fd)
                finally:
                    os.close(quarantine_fd)
            except (OSError, ValueError, json.JSONDecodeError):
                # Unknown ownership, liveness, or a failed cleanup preserves
                # the candidate and never suppresses the current pytest run.
                pass
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if parent_lock is not None:
                    os.close(parent_lock)
                if quarantine is not None and quarantine_identity is not None:
                    try:
                        named = os.stat(quarantine.name, dir_fd=parent_fd, follow_symlinks=False)
                        if ((named.st_dev, named.st_ino) == quarantine_identity
                                and _same_temp_mount(parent, parent_fd, mount)):
                            os.rmdir(quarantine.name, dir_fd=parent_fd)
                    except OSError:
                        pass
    finally:
        os.close(parent_fd)


def pytest_configure(config) -> None:
    # Allocate before collection and tmp_path setup. An inherited debug root is
    # a parent, never a namespace to reuse (including in nested pytest runs).
    try:
        previous_root = os.environ.get("PYTEST_DEBUG_TEMPROOT")
        parent = (Path(previous_root).resolve(strict=True) if previous_root
                  else _private_temp_parent(Path(tempfile.gettempdir()).resolve(strict=True)))
        ancestors = _temp_parent_locks(parent)
        parent_lock = None
        cleanup_allowed = _qualified_temp_parent(parent)
        try:
            if cleanup_allowed:
                try:
                    parent_lock, _ = _lock_temp_parent(parent, wait=True)
                except _TempParentBusy:
                    raise
                except OSError:
                    if not previous_root:
                        raise
                    # An inherited parent with an unqualified lock remains a
                    # valid isolation parent but is never a cleanup authority.
                    cleanup_allowed = False
            namespace = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=parent)).resolve(strict=True)
            probe = namespace / ".write-probe"
            probe.write_bytes(b"pytest temporary-root isolation")
            if probe.read_bytes() != b"pytest temporary-root isolation":
                raise OSError("namespace write/read validation failed")
            probe.unlink()
            info = namespace.stat()
            marker = os.open(namespace / _TEMP_OWNER, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                             | os.O_CLOEXEC, 0o600)
            try:
                os.fchmod(marker, 0o600)
                fcntl.flock(marker, fcntl.LOCK_SH | fcntl.LOCK_NB)
                raw = (json.dumps({"version": 1, "pid": os.getpid(), "created_ns": time.time_ns(),
                                   "device": info.st_dev, "inode": info.st_ino}, sort_keys=True) + "\n").encode()
                if os.write(marker, raw) != len(raw):
                    raise OSError("short pytest owner marker write")
                config._agentic_temp_locks = ancestors
                config._agentic_temp_marker = marker
                config._agentic_temp_owner = {"version": 1, "pid": os.getpid(),
                                              "device": info.st_dev, "inode": info.st_ino}
                config._agentic_temp_previous = previous_root
                config._agentic_temp_namespace = str(namespace)
            except BaseException:
                os.close(marker)
                raise
        finally:
            if parent_lock is not None:
                os.close(parent_lock)
        if cleanup_allowed:
            _prune_expired_temp_roots(parent)
    except OSError as exc:
        for descriptor, root_fd, _ in locals().get("ancestors", []):
            os.close(root_fd)
            os.close(descriptor)
        raise pytest.UsageError(f"pytest temporary-root isolation failed: {exc}") from exc
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(namespace)

    # Sanitize vault-related environment variables BEFORE test collection to prevent
    # modules from accessing real vault paths during import. This protects against hangs
    # when vault paths are on iCloud sync or other slow filesystems.
    # See: https://github.com/RasmusTho/agentic-pkm-mvp/issues/316
    os.environ.pop("VAULT_ROOT", None)
    os.environ.pop("PANEL_ACTION_WIRING_PATH", None)

    # Provide marker definitions for pytest when pyproject/pytest.ini is ignored.
    markers = {
        "not_pg": "marks tests that do not require Postgres",
        "alpha_llm": "alpha LLM tests (require live providers)",
        "alpha_llm_live": "live alpha LLM tests",
        "eval": "evaluation/deepeval tests",
        "e2e": "end-to-end scenarios",
        "human_uat": "human-need acceptance scenarios",
        "uat_integrated_runtime": "no-mock Integrated Runtime v1 golden-path UAT over the test channel",
        "panel_llm_e2e": "panel + LLM e2e tests",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")

    timeout = getattr(config.option, "faulthandler_timeout", None)
    if timeout is not None:
        # Map CLI alias to the ini setting used by pytest's faulthandler plugin.
        config._inicache["faulthandler_timeout"] = timeout


def pytest_unconfigure(config) -> None:
    marker = getattr(config, "_agentic_temp_marker", None)
    namespace = getattr(config, "_agentic_temp_namespace", None)
    owner = getattr(config, "_agentic_temp_owner", None)
    if marker is not None and namespace is not None and owner is not None:
        try:
            root_fd = os.open(namespace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                info = os.fstat(root_fd)
                if (info.st_dev, info.st_ino) != (owner["device"], owner["inode"]):
                    raise OSError("pytest namespace changed")
                finished_fd = os.open(_TEMP_FINISHED, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                      | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
                try:
                    os.fchmod(finished_fd, 0o600)
                    raw = (json.dumps({**owner, "finished_ns": time.time_ns()}, sort_keys=True) + "\n").encode()
                    if os.write(finished_fd, raw) != len(raw):
                        raise OSError("short pytest terminal marker write")
                    os.fsync(finished_fd)
                finally:
                    os.close(finished_fd)
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        except OSError:
            # A missing or incomplete terminal marker retains this namespace.
            pass
        finally:
            os.close(marker)
    for descriptor, root_fd, child_name in getattr(config, "_agentic_temp_locks", ()):
        try:
            os.utime(descriptor, None)
            os.fsync(descriptor)
            os.unlink(child_name, dir_fd=root_fd)
            os.fsync(root_fd)
        except OSError:
            # A failed timestamp leaves the child marker; after unlink the
            # already-synced timestamp still preserves the retention window.
            pass
        finally:
            os.close(root_fd)
            os.close(descriptor)
    if os.environ.get("PYTEST_DEBUG_TEMPROOT") == getattr(config, "_agentic_temp_namespace", None):
        previous = getattr(config, "_agentic_temp_previous", None)
        if previous is None:
            os.environ.pop("PYTEST_DEBUG_TEMPROOT", None)
        else:
            os.environ["PYTEST_DEBUG_TEMPROOT"] = previous


@pytest.fixture(autouse=True)
def _sanitize_external_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ensure tests are hermetic and do not accidentally read from a user's real vault
    (e.g. iCloud-backed VAULT_ROOT), which can block filesystem opens and hang the suite.

    Any test that needs these variables must set them explicitly via monkeypatch.
    """
    # Prevent accidental reads from a real vault.
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)

    # Deterministic defaults.
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("LLM_EMBED_MODEL", "mock-embed")

    # pg-marked tests must see the environment-provided DATABASE_URL (CI
    # service container, local scratch DB); stripping it here made every pg
    # test in CI skip or fail (#2818). There is no fallback to strip through
    # any more — the pg lane is explicit-or-nothing (#4573). Same guard pattern
    # as tests/conftest.py::force_memory_store_for_non_pg.
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)

    # Eval tests remain opt-in.
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
