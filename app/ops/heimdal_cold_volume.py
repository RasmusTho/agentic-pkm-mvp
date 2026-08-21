"""Fail-closed host boundary for Heimdal's encrypted cold volume (HAR-03).

This module provisions or validates one encrypted APFS sparsebundle.  It never
copies raw evidence, changes retention, or activates a raw representation.
Host commands are closed and machine-readable; callers cannot supply an
arbitrary executable, verb, raw device, parent-volume target, or shell string.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import stat
import subprocess
import sys
import threading
import unicodedata

from app.ops.host_secret_bootstrap import (
    HOST_SECRET_BOOTSTRAP_CHANNEL,
    HOST_SECRET_BOOTSTRAP_CONSUMER,
    load_runtime_secret_values,
    validate_secret_value,
)


HDIUTIL = "/usr/bin/hdiutil"
DISKUTIL = "/usr/sbin/diskutil"
MAX_PLIST_BYTES = 1024 * 1024
MAX_IMAGE_METADATA_BYTES = 256 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_CHANNEL_CONFIG_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 60.0
MAX_CAPACITY_BYTES = 2**63 - 512
ARCHIVE_SECRET = "heimdal.archive-pass"
ARCHIVE_SECRET_BINDING = "HEIMDAL_ARCHIVE_PASS"
PLANNED_UNBOUND = "planned-unbound"
PROVISIONING_FAILED = "provisioning-failed"
ATTACHED_VERIFIED = "attached-verified"
BOUND_ACTIVE = "bound-active"
_METADATA_STATES = frozenset(
    {PLANNED_UNBOUND, PROVISIONING_FAILED, ATTACHED_VERIFIED, BOUND_ACTIVE}
)
_CHANNELS = frozenset({"dev", "test", "prod"})
_METADATA_CONFIG_KEY = "HEIMDAL_ARCHIVE_METADATA_FILE"
_ARCHIVE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_UUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
_DEVICE = re.compile(r"^/dev/disk[0-9][0-9A-Za-z._-]*$")
_DEVICE_IDENTIFIER = re.compile(r"^disk[0-9][0-9A-Za-z._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEYS = frozenset(
    {
        "generation",
        "state",
        "channel",
        "archive_id",
        "bundle_path",
        "mountpoint",
        "parent_volume_uuid",
        "bundle_inode",
        "image_metadata_sha256",
        "volume_uuid",
        "capacity_bytes",
        "filesystem_capacity_bytes",
        "owner_uid",
        "owner_gid",
        "mode",
    }
)
_DISK_KEYS = frozenset(
    {
        "DeviceIdentifier",
        "MountPoint",
        "VolumeUUID",
        "FilesystemType",
        "TotalSize",
        "Internal",
        "VolumeName",
    }
)
_PARENT_DISK_KEYS = frozenset(
    {"DeviceIdentifier", "MountPoint", "VolumeUUID", "Internal"}
)
_ONE_SHOT_DESCRIPTOR_AUTHORITY = object()
_DETACH_AUTHORITY_ISSUER = object()


class ArchiveVolumeRefusedError(RuntimeError):
    """A redacted archive-volume refusal."""


@dataclass(frozen=True)
class ArchiveVolumeMetadata:
    generation: int
    state: str
    channel: str
    archive_id: str
    bundle_path: Path
    mountpoint: Path
    parent_volume_uuid: str
    bundle_inode: int | None
    image_metadata_sha256: str | None
    volume_uuid: str | None
    capacity_bytes: int
    filesystem_capacity_bytes: int | None
    owner_uid: int
    owner_gid: int
    mode: int

    def __post_init__(self) -> None:
        if (
            type(self.generation) is not int
            or self.generation < 0
            or type(self.state) is not str
            or self.state not in _METADATA_STATES
            or self.generation
            != {
                PLANNED_UNBOUND: 0,
                PROVISIONING_FAILED: 1,
                ATTACHED_VERIFIED: 2,
                BOUND_ACTIVE: 3,
            }[self.state]
            or type(self.channel) is not str
            or self.channel not in _CHANNELS
            or type(self.archive_id) is not str
            or _ARCHIVE_ID.fullmatch(self.archive_id) is None
            or not isinstance(self.bundle_path, Path)
            or not self.bundle_path.is_absolute()
            or self.bundle_path.suffix != ".sparsebundle"
            or not isinstance(self.mountpoint, Path)
            or not self.mountpoint.is_absolute()
            or self.bundle_path == self.bundle_path.parent
            or self.mountpoint == self.mountpoint.parent
            or self.mountpoint == self.bundle_path.parent
            or type(self.parent_volume_uuid) is not str
            or _UUID.fullmatch(self.parent_volume_uuid) is None
            or type(self.capacity_bytes) is not int
            or self.capacity_bytes <= 0
            or self.capacity_bytes > MAX_CAPACITY_BYTES
            or self.capacity_bytes % 512 != 0
            or (
                self.state == PLANNED_UNBOUND
                and (
                    self.volume_uuid is not None
                    or self.bundle_inode is not None
                    or self.image_metadata_sha256 is not None
                    or self.filesystem_capacity_bytes is not None
                )
            )
            or (
                self.state == PROVISIONING_FAILED
                and (
                    self.volume_uuid is not None
                    or type(self.bundle_inode) is not int
                    or self.bundle_inode <= 0
                    or type(self.image_metadata_sha256) is not str
                    or _SHA256.fullmatch(self.image_metadata_sha256) is None
                    or self.filesystem_capacity_bytes is not None
                )
            )
            or (
                self.state in {ATTACHED_VERIFIED, BOUND_ACTIVE}
                and (
                    type(self.volume_uuid) is not str
                    or _UUID.fullmatch(self.volume_uuid) is None
                    or type(self.bundle_inode) is not int
                    or self.bundle_inode <= 0
                    or type(self.image_metadata_sha256) is not str
                    or _SHA256.fullmatch(self.image_metadata_sha256) is None
                    or type(self.filesystem_capacity_bytes) is not int
                    or self.filesystem_capacity_bytes <= 0
                    or self.filesystem_capacity_bytes > self.capacity_bytes
                    or self.filesystem_capacity_bytes % 512 != 0
                )
            )
            or type(self.owner_uid) is not int
            or self.owner_uid < 0
            or type(self.owner_gid) is not int
            or self.owner_gid < 0
            or type(self.mode) is not int
            or self.mode != 0o700
        ):
            raise ArchiveVolumeRefusedError("archive volume metadata is invalid")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""
    cwd_identity: tuple[int, int] | None = None


_ARCHIVE_VOLUME_READY_ISSUER = object()


@dataclass(frozen=True, init=False)
class ArchiveVolumeReady:
    ready: bool
    archive_ref: str
    mountpoint: Path
    _issuer: object

    def __init__(self, *, _issuer: object, archive_ref: str, mountpoint: Path) -> None:
        if _issuer is not _ARCHIVE_VOLUME_READY_ISSUER:
            raise _refused()
        if not mountpoint.is_absolute():
            raise _refused()
        object.__setattr__(self, "ready", True)
        object.__setattr__(self, "archive_ref", archive_ref)
        object.__setattr__(self, "mountpoint", mountpoint)
        object.__setattr__(self, "_issuer", _issuer)


def _issue_archive_volume_ready(archive_ref: str, mountpoint: Path) -> ArchiveVolumeReady:
    """Issue a proof for the verified-volume boundary and its bound archive."""
    return ArchiveVolumeReady(
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
        archive_ref=archive_ref,
        mountpoint=mountpoint,
    )


CommandRunner = Callable[..., CommandResult]
Executor = Callable[..., subprocess.CompletedProcess[bytes]]
MetadataWriter = Callable[[Path, ArchiveVolumeMetadata], None]


@dataclass(frozen=True)
class _DetachAuthority:
    """Private proof that one successful attach returned this exact device."""

    device: str
    issuer: object

    def __post_init__(self) -> None:
        if (
            self.issuer is not _DETACH_AUTHORITY_ISSUER
            or type(self.device) is not str
            or _DEVICE.fullmatch(self.device) is None
        ):
            raise _refused()


def _refused() -> ArchiveVolumeRefusedError:
    return ArchiveVolumeRefusedError("archive volume is not ready")


def _fchdir_preexec(descriptor: int) -> Callable[[], None]:
    """Return the only child hook used by the one-shot provisioner."""

    def enter_verified_parent() -> None:
        os.fchdir(descriptor)

    return enter_verified_parent


def _run_closed_child(
    argv: tuple[str, ...],
    *,
    stdin: bytes | None,
    timeout_seconds: float,
    executor: Executor,
    cwd_fd: int | None,
) -> subprocess.CompletedProcess[bytes]:
    extra: dict[str, object] = {}
    if cwd_fd is not None:
        # preexec_fn is safe here only because provisioning is a short-lived,
        # single-threaded CLI action. Refuse imported/threaded runtime use.
        if (
            threading.current_thread() is not threading.main_thread()
            or threading.active_count() != 1
        ):
            raise _refused()
        extra = {
            "pass_fds": (cwd_fd,),
            "preexec_fn": _fchdir_preexec(cwd_fd),
        }
    return executor(
        list(argv),
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
        env={"PATH": "/usr/bin:/usr/sbin"},
        **extra,
    )


def _safe_path(path: Path) -> Path:
    try:
        if path.is_symlink():
            raise _refused()
        return path.resolve(strict=False)
    except OSError as exc:
        raise _refused() from exc


def _require_exact_path_spelling(path: Path) -> os.stat_result:
    """Open each component without symlinks and require its exact directory spelling."""
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise _refused()
    descriptor = -1
    try:
        descriptor = os.open(
            os.sep,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        components = path.parts[1:]
        for index, component in enumerate(components):
            if component in {"", ".", ".."}:
                raise _refused()
            entries = os.listdir(descriptor)
            normalized = unicodedata.normalize("NFC", component).casefold()
            if component not in entries or sum(
                unicodedata.normalize("NFC", entry).casefold() == normalized
                for entry in entries
            ) != 1:
                raise _refused()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if index < len(components) - 1:
                flags |= getattr(os, "O_DIRECTORY", 0)
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return os.fstat(descriptor)
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _path_key(path: Path) -> str:
    return os.path.normcase(str(_safe_path(path))).casefold()


def _metadata_dict(metadata: ArchiveVolumeMetadata) -> dict[str, object]:
    payload = asdict(metadata)
    payload["bundle_path"] = str(metadata.bundle_path)
    payload["mountpoint"] = str(metadata.mountpoint)
    return payload


def _metadata_bytes(metadata: ArchiveVolumeMetadata) -> bytes:
    return (json.dumps(_metadata_dict(metadata), sort_keys=True) + "\n").encode("utf-8")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise _refused()
        payload[key] = value
    return payload


_METADATA_LOCK_STATE = threading.local()


@contextmanager
def _metadata_lock(path: Path) -> Iterator[int]:
    """Hold the descriptor-bound adjacent lock for one metadata transaction."""
    if not path.is_absolute() or path.is_symlink() or path.name in {"", ".", ".."}:
        raise _refused()
    key = str(path)
    held: dict[str, int] = getattr(_METADATA_LOCK_STATE, "held", {})
    if key in held:
        yield held[key]
        return

    parent_descriptor = -1
    lock_descriptor = -1
    try:
        parent = path.parent
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        held_parent = os.fstat(parent_descriptor)
        live_parent = os.stat(parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(held_parent.st_mode)
            or not os.path.samestat(held_parent, live_parent)
        ):
            raise _refused()
        lock_name = f".{path.name}.lock"
        lock_descriptor = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(lock_descriptor, 0o600)
        lock_details = os.fstat(lock_descriptor)
        if (
            not stat.S_ISREG(lock_details.st_mode)
            or stat.S_IMODE(lock_details.st_mode) != 0o600
            or lock_details.st_uid != os.geteuid()
        ):
            raise _refused()
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        held[key] = parent_descriptor
        _METADATA_LOCK_STATE.held = held
        yield parent_descriptor
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        held.pop(key, None)
        if lock_descriptor >= 0:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _read_metadata_bytes(parent_descriptor: int, name: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size <= 0
            or details.st_size > MAX_METADATA_BYTES
        ):
            raise _refused()
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise _refused()
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise _refused()
        return b"".join(chunks)
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_metadata_bytes(parent_descriptor: int, name: str, payload: bytes) -> None:
    temporary = f".{name}.{secrets.token_hex(16)}"
    descriptor = -1
    try:
        try:
            current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current is not None and (
            not stat.S_ISREG(current.st_mode) or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise _refused()
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise _refused()
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary,
            name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def write_archive_metadata(path: Path, metadata: ArchiveVolumeMetadata) -> None:
    """Create initial metadata, or write only inside an authorized transition lock."""
    held: dict[str, int] = getattr(_METADATA_LOCK_STATE, "held", {})
    transition_authorized = str(path) in held
    with _metadata_lock(path) as parent_descriptor:
        if not transition_authorized:
            try:
                os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise _refused() from exc
            else:
                raise _refused()
        _write_metadata_bytes(parent_descriptor, path.name, _metadata_bytes(metadata))


def load_archive_metadata(path: Path) -> ArchiveVolumeMetadata:
    if not path.is_absolute() or path.is_symlink():
        raise _refused()
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
            or details.st_size <= 0
            or details.st_size > MAX_METADATA_BYTES
        ):
            raise _refused()
        raw = b""
        while len(raw) < details.st_size:
            chunk = os.read(descriptor, details.st_size - len(raw))
            if not chunk:
                raise _refused()
            raw += chunk
        if os.read(descriptor, 1):
            raise _refused()
        after = os.fstat(descriptor)
        live = os.stat(path, follow_symlinks=False)
        if (
            not os.path.samestat(details, after)
            or not os.path.samestat(after, live)
        ):
            raise _refused()
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except ArchiveVolumeRefusedError:
        raise
    except Exception as exc:
        raise _refused() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict) or set(payload) != _METADATA_KEYS:
        raise _refused()
    try:
        metadata = ArchiveVolumeMetadata(
            generation=payload["generation"],
            state=payload["state"],
            channel=payload["channel"],
            archive_id=payload["archive_id"],
            bundle_path=Path(payload["bundle_path"]),
            mountpoint=Path(payload["mountpoint"]),
            parent_volume_uuid=payload["parent_volume_uuid"],
            bundle_inode=payload["bundle_inode"],
            image_metadata_sha256=payload["image_metadata_sha256"],
            volume_uuid=payload["volume_uuid"],
            capacity_bytes=payload["capacity_bytes"],
            filesystem_capacity_bytes=payload["filesystem_capacity_bytes"],
            owner_uid=payload["owner_uid"],
            owner_gid=payload["owner_gid"],
            mode=payload["mode"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _refused() from exc
    if raw != _metadata_bytes(metadata):
        raise _refused()
    return metadata


def _read_channel_metadata_declaration(
    config_path: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> str:
    descriptor = -1
    try:
        descriptor = os.open(
            config_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_size <= 0
            or details.st_size > MAX_CHANNEL_CONFIG_BYTES
            or (
                expected_identity is not None
                and (details.st_dev, details.st_ino) != expected_identity
            )
        ):
            raise _refused()
        raw = os.read(descriptor, details.st_size + 1)
        if len(raw) != details.st_size:
            raise _refused()
        after = os.fstat(descriptor)
        live = os.stat(config_path, follow_symlinks=False)
        if (
            not os.path.samestat(details, after)
            or not os.path.samestat(after, live)
        ):
            raise _refused()
        text = raw.decode("utf-8", errors="strict")
    except ArchiveVolumeRefusedError:
        raise
    except (OSError, UnicodeError) as exc:
        raise _refused() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    declared: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator and name.strip() == _METADATA_CONFIG_KEY:
            candidate = value.strip()
            if (
                len(candidate) >= 2
                and candidate[0] == candidate[-1]
                and candidate[0] in {"'", '"'}
            ):
                candidate = candidate[1:-1]
            declared.append(candidate)
    if len(declared) != 1 or not declared[0]:
        raise _refused()
    return declared[0]


def _channel_archive_metadata_authority(
    *,
    config_root: Path,
    channel: str,
    env: Mapping[str, str] | None = None,
) -> tuple[Path, ArchiveVolumeMetadata]:
    if (
        channel not in _CHANNELS
        or not config_root.is_absolute()
        or config_root.is_symlink()
    ):
        raise _refused()
    root_details = _require_exact_path_spelling(config_root)
    if not stat.S_ISDIR(root_details.st_mode):
        raise _refused()

    config_path = config_root / f".env.{channel}.local"
    config_details = _require_exact_path_spelling(config_path)
    declared = _read_channel_metadata_declaration(
        config_path,
        expected_identity=(config_details.st_dev, config_details.st_ino),
    )
    source = os.environ if env is None else env
    ambient = source.get(_METADATA_CONFIG_KEY)
    if ambient is not None and ambient != declared:
        raise _refused()

    metadata_path = Path(declared)
    if (
        not metadata_path.is_absolute()
        or metadata_path.is_symlink()
        or os.path.normpath(declared) != declared
    ):
        raise _refused()
    _require_exact_path_spelling(metadata_path)
    metadata = load_archive_metadata(metadata_path)
    if metadata.channel != channel:
        raise _refused()
    return metadata_path, metadata


def load_channel_archive_metadata(
    *,
    config_root: Path,
    channel: str,
    env: Mapping[str, str] | None = None,
) -> ArchiveVolumeMetadata:
    """Load the one channel-governed metadata file without ambient path authority."""
    return _channel_archive_metadata_authority(
        config_root=config_root,
        channel=channel,
        env=env,
    )[1]


def _require_expected_channel(
    metadata: ArchiveVolumeMetadata,
    expected_channel: str | None,
) -> None:
    if expected_channel is not None and (
        expected_channel not in _CHANNELS or metadata.channel != expected_channel
    ):
        raise _refused()


def create_command(metadata: ArchiveVolumeMetadata) -> tuple[str, ...]:
    """Return the descriptor-relative creation grammar (no source or overwrite)."""
    return (
        HDIUTIL,
        "create",
        "-sectors",
        str(metadata.capacity_bytes // 512),
        "-type",
        "SPARSEBUNDLE",
        "-fs",
        "APFS",
        "-volname",
        metadata.archive_id,
        "-uid",
        str(metadata.owner_uid),
        "-gid",
        str(metadata.owner_gid),
        "-mode",
        f"{metadata.mode:o}",
        "-encryption",
        "AES-256",
        "-stdinpass",
        "-plist",
        metadata.bundle_path.name,
    )


def attach_command(metadata: ArchiveVolumeMetadata) -> tuple[str, ...]:
    return (
        HDIUTIL,
        "attach",
        "-stdinpass",
        "-plist",
        "-nobrowse",
        "-owners",
        "on",
        "-mountpoint",
        str(metadata.mountpoint),
        metadata.bundle_path.name,
    )


def _encrypted_command(metadata: ArchiveVolumeMetadata) -> tuple[str, ...]:
    return (HDIUTIL, "isencrypted", metadata.bundle_path.name, "-plist")


def validate_command(
    argv: tuple[str, ...],
    metadata: ArchiveVolumeMetadata,
    *,
    cwd_fd: int | None = None,
) -> None:
    allowed = {
        (HDIUTIL, "info", "-plist"),
        (DISKUTIL, "info", "-plist", str(metadata.bundle_path.parent)),
    }
    if argv in allowed:
        return
    if argv in {
        create_command(metadata),
        attach_command(metadata),
        _encrypted_command(metadata),
    }:
        if (
            type(cwd_fd) is not int
            or cwd_fd < 0
            or Path(argv[-1]).name != argv[-1]
            or "/" in argv[-1]
        ):
            raise _refused()
        return
    if argv[:4] == (DISKUTIL, "info", "-plist") and len(argv) == 4:
        if _DEVICE.fullmatch(argv[3]) is not None:
            return
    raise _refused()


def run_command(
    argv: tuple[str, ...],
    metadata: ArchiveVolumeMetadata,
    stdin: bytes | None = None,
    cwd_fd: int | None = None,
    *,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    executor: Executor = subprocess.run,
    _descriptor_authority: object | None = None,
) -> CommandResult:
    validate_command(argv, metadata, cwd_fd=cwd_fd)
    cwd_identity: tuple[int, int] | None = None
    if cwd_fd is not None:
        if _descriptor_authority is not _ONE_SHOT_DESCRIPTOR_AUTHORITY:
            raise _refused()
        try:
            before = os.fstat(cwd_fd)
        except OSError as exc:
            raise _refused() from exc
        if not stat.S_ISDIR(before.st_mode):
            raise _refused()
        cwd_identity = (before.st_dev, before.st_ino)
    try:
        completed = _run_closed_child(
            argv,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            executor=executor,
            cwd_fd=cwd_fd,
        )
    except Exception as exc:
        raise _refused() from exc
    stdout = bytes(completed.stdout or b"")
    stderr = bytes(completed.stderr or b"")
    if len(stdout) > MAX_PLIST_BYTES or len(stderr) > MAX_PLIST_BYTES:
        raise _refused()
    if cwd_fd is not None:
        try:
            after = os.fstat(cwd_fd)
        except OSError as exc:
            raise _refused() from exc
        if cwd_identity != (after.st_dev, after.st_ino):
            raise _refused()
    return CommandResult(int(completed.returncode), stdout, stderr, cwd_identity)


@dataclass(frozen=True)
class _DefaultCommandRunner:
    metadata: ArchiveVolumeMetadata
    descriptor_authority: object | None

    def __call__(
        self,
        argv: tuple[str, ...],
        stdin: bytes | None = None,
        cwd_fd: int | None = None,
    ) -> CommandResult:
        return run_command(
            argv,
            self.metadata,
            stdin,
            cwd_fd,
            _descriptor_authority=self.descriptor_authority,
        )

    def detach(self, authority: _DetachAuthority) -> CommandResult:
        return _run_private_detach(authority)


def _runner(
    metadata: ArchiveVolumeMetadata,
    *,
    descriptor_authority: object | None = None,
) -> CommandRunner:
    return _DefaultCommandRunner(metadata, descriptor_authority)


def _run_private_detach(
    authority: _DetachAuthority,
    *,
    executor: Executor = subprocess.run,
) -> CommandResult:
    """Execute detach only with the capability created from attach output."""
    if (
        not isinstance(authority, _DetachAuthority)
        or authority.issuer is not _DETACH_AUTHORITY_ISSUER
        or _DEVICE.fullmatch(authority.device) is None
    ):
        raise _refused()
    argv = (HDIUTIL, "detach", authority.device)
    try:
        completed = _run_closed_child(
            argv,
            stdin=None,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
            executor=executor,
            cwd_fd=None,
        )
    except Exception as exc:
        raise _refused() from exc
    stdout = bytes(completed.stdout or b"")
    stderr = bytes(completed.stderr or b"")
    if len(stdout) > MAX_PLIST_BYTES or len(stderr) > MAX_PLIST_BYTES:
        raise _refused()
    return CommandResult(int(completed.returncode), stdout, stderr)


def _call(
    runner: CommandRunner,
    argv: tuple[str, ...],
    stdin: bytes | None = None,
    *,
    cwd_fd: int | None = None,
) -> CommandResult:
    expected_cwd_identity: tuple[int, int] | None = None
    if cwd_fd is not None:
        try:
            before = os.fstat(cwd_fd)
        except OSError as exc:
            raise _refused() from exc
        if not stat.S_ISDIR(before.st_mode):
            raise _refused()
        expected_cwd_identity = (before.st_dev, before.st_ino)
    try:
        if cwd_fd is None:
            result = runner(argv, stdin)
        else:
            result = runner(argv, stdin, cwd_fd)
    except Exception as exc:
        raise _refused() from exc
    if (
        type(result.returncode) is not int
        or not isinstance(result.stdout, bytes)
        or not isinstance(result.stderr, bytes)
        or result.returncode != 0
        or len(result.stdout) > MAX_PLIST_BYTES
        or len(result.stderr) > MAX_PLIST_BYTES
    ):
        raise _refused()
    if cwd_fd is None:
        if result.cwd_identity is not None:
            raise _refused()
    else:
        try:
            after = os.fstat(cwd_fd)
        except OSError as exc:
            raise _refused() from exc
        if (
            type(result.cwd_identity) is not tuple
            or len(result.cwd_identity) != 2
            or any(type(part) is not int for part in result.cwd_identity)
            or result.cwd_identity != expected_cwd_identity
            or (after.st_dev, after.st_ino) != expected_cwd_identity
        ):
            raise _refused()
    return result


def _parse_plist(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > MAX_PLIST_BYTES:
        raise _refused()
    try:
        payload = plistlib.loads(raw)
    except Exception as exc:
        raise _refused() from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise _refused()
    return payload


def _reported_bundle_identity(path: Path) -> tuple[int, int] | None:
    """Open every absolute path component without symlinks and return final identity."""
    if not path.is_absolute():
        return None
    descriptor = -1
    try:
        components = path.parts
        if not components or components[0] != os.sep:
            return None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(os.sep, flags)
        for component in components[1:]:
            if component == "":
                return None
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            return None
        return details.st_dev, details.st_ino
    except (OSError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _attached_device(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    *,
    bundle_identity: tuple[int, int] | None = None,
) -> str | None:
    payload = _parse_plist(_call(runner, (HDIUTIL, "info", "-plist")).stdout)
    if "images" not in payload or not isinstance(payload["images"], list):
        raise _refused()
    matches: list[dict[str, object]] = []
    foreign_mountpoint = False
    expected_bundle = _path_key(metadata.bundle_path)
    expected_mountpoint = _path_key(metadata.mountpoint)
    for raw_image in payload["images"]:
        if not isinstance(raw_image, dict):
            raise _refused()
        image_path = raw_image.get("image-path")
        entities = raw_image.get("system-entities")
        if not isinstance(image_path, str) or not isinstance(entities, list):
            raise _refused()
        image_matches = (
            _path_key(Path(image_path)) == expected_bundle
            if bundle_identity is None
            else _reported_bundle_identity(Path(image_path)) == bundle_identity
        )
        if image_matches:
            matches.append(raw_image)
        for raw_entity in entities:
            if not isinstance(raw_entity, dict):
                raise _refused()
            raw_mountpoint = raw_entity.get("mount-point")
            if raw_mountpoint is None:
                continue
            if not isinstance(raw_mountpoint, str):
                raise _refused()
            if _path_key(Path(raw_mountpoint)) == expected_mountpoint and not image_matches:
                foreign_mountpoint = True
    if foreign_mountpoint:
        raise _refused()
    if not matches:
        return None
    if len(matches) != 1:
        raise _refused()
    entities = matches[0]["system-entities"]
    if not isinstance(entities, list):
        raise _refused()
    entity_matches: list[str] = []
    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            raise _refused()
        if not {"dev-entry", "mount-point"}.issubset(raw_entity):
            continue
        device = raw_entity["dev-entry"]
        mountpoint = raw_entity["mount-point"]
        if not isinstance(device, str) or not isinstance(mountpoint, str):
            raise _refused()
        if _path_key(Path(mountpoint)) == expected_mountpoint:
            if _DEVICE.fullmatch(device) is None:
                raise _refused()
            entity_matches.append(device)
    if len(entity_matches) != 1:
        raise _refused()
    return entity_matches[0]


def _device_from_attach_response(
    metadata: ArchiveVolumeMetadata,
    raw: bytes,
) -> _DetachAuthority:
    """Extract the one newly attached mounted device from typed plist output."""
    payload = _parse_plist(raw)
    entities = payload.get("system-entities")
    if not isinstance(entities, list):
        raise _refused()
    expected_mountpoint = _path_key(metadata.mountpoint)
    matches: list[str] = []
    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            raise _refused()
        device = raw_entity.get("dev-entry")
        mountpoint = raw_entity.get("mount-point")
        if mountpoint is None:
            if device is not None and not isinstance(device, str):
                raise _refused()
            continue
        if not isinstance(device, str) or not isinstance(mountpoint, str):
            raise _refused()
        if _path_key(Path(mountpoint)) == expected_mountpoint:
            if _DEVICE.fullmatch(device) is None:
                raise _refused()
            matches.append(device)
    if len(matches) != 1:
        raise _refused()
    return _DetachAuthority(matches[0], _DETACH_AUTHORITY_ISSUER)


def _require_bundle_directory(metadata: ArchiveVolumeMetadata) -> None:
    try:
        details = os.lstat(metadata.bundle_path)
    except OSError as exc:
        raise _refused() from exc
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise _refused()


def _open_mount_directory(metadata: ArchiveVolumeMetadata) -> int:
    descriptor = -1
    try:
        descriptor = os.open(
            metadata.mountpoint,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise _refused() from exc
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != metadata.owner_uid
        or details.st_gid != metadata.owner_gid
        or stat.S_IMODE(details.st_mode) != metadata.mode
    ):
        os.close(descriptor)
        raise _refused()
    return descriptor


def _revalidate_directory(descriptor: int, path: Path) -> None:
    try:
        held = os.fstat(descriptor)
        live = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise _refused() from exc
    if not os.path.samestat(held, live):
        raise _refused()


def _require_empty_mount_directory(metadata: ArchiveVolumeMetadata) -> None:
    descriptor = _open_mount_directory(metadata)
    try:
        if os.listdir(descriptor):
            raise _refused()
        _revalidate_directory(descriptor, metadata.mountpoint)
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        os.close(descriptor)


def _open_external_parent(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
) -> int:
    parent_descriptor = -1
    parent = metadata.bundle_path.parent
    try:
        if parent.is_symlink():
            raise _refused()
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(parent_descriptor)
        payload = _parse_plist(
            _call(
                runner,
                (DISKUTIL, "info", "-plist", str(parent)),
            ).stdout
        )
        after = os.fstat(parent_descriptor)
        live = os.stat(parent, follow_symlinks=False)
        if not os.path.samestat(before, after) or not os.path.samestat(after, live):
            raise _refused()
        if not _PARENT_DISK_KEYS.issubset(payload):
            raise _refused()
        identifier = payload["DeviceIdentifier"]
        mountpoint = payload["MountPoint"]
        parent_volume_uuid = payload["VolumeUUID"]
        if (
            type(identifier) is not str
            or _DEVICE_IDENTIFIER.fullmatch(identifier) is None
            or type(mountpoint) is not str
            or not Path(mountpoint).is_absolute()
            or type(parent_volume_uuid) is not str
            or _UUID.fullmatch(parent_volume_uuid) is None
            or parent_volume_uuid.upper() != metadata.parent_volume_uuid.upper()
            or payload["Internal"] is not False
            or _path_key(parent) != _path_key(Path(mountpoint))
        ):
            raise _refused()
        return parent_descriptor
    except ArchiveVolumeRefusedError:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        raise
    except OSError as exc:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        raise _refused() from exc


def _require_external_parent(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
) -> None:
    parent_descriptor = _open_external_parent(metadata, runner)
    os.close(parent_descriptor)


def _revalidate_external_parent(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    held_descriptor: int,
) -> None:
    """Re-prove the live external root and UUID against the held directory."""
    live_descriptor = _open_external_parent(metadata, runner)
    try:
        if not os.path.samestat(os.fstat(held_descriptor), os.fstat(live_descriptor)):
            raise _refused()
    except OSError as exc:
        raise _refused() from exc
    finally:
        os.close(live_descriptor)


def _require_encrypted(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    parent_descriptor: int,
) -> None:
    payload = _parse_plist(
        _call(
            runner,
            _encrypted_command(metadata),
            cwd_fd=parent_descriptor,
        ).stdout
    )
    if "encrypted" not in payload or payload["encrypted"] is not True:
        raise _refused()


def _require_disk_info(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    device: str,
) -> tuple[str, int]:
    payload = _parse_plist(
        _call(runner, (DISKUTIL, "info", "-plist", device)).stdout
    )
    if not _DISK_KEYS.issubset(payload):
        raise _refused()
    volume_uuid = payload["VolumeUUID"]
    filesystem_capacity = payload["TotalSize"]
    if (
        payload["DeviceIdentifier"] != device.removeprefix("/dev/")
        or payload["MountPoint"] != str(metadata.mountpoint)
        or type(volume_uuid) is not str
        or _UUID.fullmatch(volume_uuid) is None
        or payload["FilesystemType"] != "apfs"
        or type(filesystem_capacity) is not int
        or filesystem_capacity <= 0
        or filesystem_capacity > metadata.capacity_bytes
        or filesystem_capacity % 512 != 0
        or (
            metadata.filesystem_capacity_bytes is not None
            and filesystem_capacity != metadata.filesystem_capacity_bytes
        )
        or payload["Internal"] is not False
        or payload["VolumeName"] != metadata.archive_id
    ):
        raise _refused()
    canonical_uuid = volume_uuid.upper()
    if metadata.volume_uuid is not None and canonical_uuid != metadata.volume_uuid.upper():
        raise _refused()
    return canonical_uuid, filesystem_capacity


def require_archive_volume_ready(
    metadata: ArchiveVolumeMetadata,
    *,
    expected_channel: str | None = None,
    runner: CommandRunner | None = None,
    _descriptor_authority: object | None = None,
) -> ArchiveVolumeReady:
    _require_expected_channel(metadata, expected_channel)
    if metadata.state != BOUND_ACTIVE:
        raise _refused()
    selected = (
        _runner(metadata, descriptor_authority=_descriptor_authority)
        if runner is None
        else runner
    )
    parent_descriptor = _open_external_parent(metadata, selected)
    try:
        bundle_identity = _require_durable_bundle_binding(parent_descriptor, metadata)
        _validate_attached_volume(
            metadata,
            selected,
            parent_descriptor,
            bundle_identity,
        )
    finally:
        os.close(parent_descriptor)
    # Startup callers use the same verified boundary to rebind cold reads
    # after a process restart; never bind an unverified mountpoint.
    from app.heimdal import raw_store

    raw_store.configure_cold_archive_root(metadata.mountpoint)
    return ArchiveVolumeReady(
        _issuer=_ARCHIVE_VOLUME_READY_ISSUER,
        archive_ref=metadata.archive_id,
        mountpoint=metadata.mountpoint,
    )


@dataclass(frozen=True)
class _Attachment:
    device: str
    volume_uuid: str
    filesystem_capacity_bytes: int
    detach_authority: _DetachAuthority | None

    @property
    def attached_here(self) -> bool:
        return self.detach_authority is not None


def _validate_attached_volume(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    parent_descriptor: int,
    bundle_identity: tuple[int, int],
) -> tuple[str, str, int]:
    _revalidate_external_parent(metadata, runner, parent_descriptor)
    if _require_durable_bundle_binding(parent_descriptor, metadata) != bundle_identity:
        raise _refused()
    mount_descriptor = _open_mount_directory(metadata)
    try:
        device = _attached_device(
            metadata,
            runner,
            bundle_identity=bundle_identity,
        )
        if device is None:
            raise _refused()
        _require_encrypted(metadata, runner, parent_descriptor)
        volume_uuid, filesystem_capacity = _require_disk_info(metadata, runner, device)
        _revalidate_directory(mount_descriptor, metadata.mountpoint)
        _revalidate_external_parent(metadata, runner, parent_descriptor)
        if _require_durable_bundle_binding(parent_descriptor, metadata) != bundle_identity:
            raise _refused()
        return device, volume_uuid, filesystem_capacity
    finally:
        os.close(mount_descriptor)


def _credential_input(credential: str) -> bytes:
    if not validate_secret_value("archive-pass", credential):
        raise _refused()
    try:
        encoded = credential.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise _refused() from exc
    if b"\x00" in encoded:
        raise _refused()
    return encoded + b"\x00"


def mount_archive_volume(
    metadata: ArchiveVolumeMetadata,
    *,
    credential: str,
    expected_channel: str | None = None,
    runner: CommandRunner | None = None,
    _descriptor_authority: object | None = None,
) -> ArchiveVolumeReady:
    _require_expected_channel(metadata, expected_channel)
    if metadata.state != BOUND_ACTIVE:
        raise _refused()
    selected = (
        _runner(metadata, descriptor_authority=_descriptor_authority)
        if runner is None
        else runner
    )
    _mount_and_validate(metadata, credential=credential, runner=selected)
    return _issue_archive_volume_ready(metadata.archive_id, metadata.mountpoint)


def _mount_and_validate(
    metadata: ArchiveVolumeMetadata,
    *,
    credential: str,
    runner: CommandRunner,
    parent_descriptor: int | None = None,
    bundle_identity: tuple[int, int] | None = None,
    require_fresh_attach: bool = False,
) -> _Attachment:
    owns_parent_descriptor = parent_descriptor is None
    if parent_descriptor is None:
        parent_descriptor = _open_external_parent(metadata, runner)
    try:
        if bundle_identity is None:
            bundle_identity = _require_durable_bundle_binding(parent_descriptor, metadata)
        elif (
            metadata.bundle_inode != bundle_identity[1]
            or metadata.image_metadata_sha256 is None
            or _image_metadata_fingerprint(parent_descriptor, metadata)
            != metadata.image_metadata_sha256
        ):
            raise _refused()
        _require_created_bundle_postcondition(
            parent_descriptor,
            metadata,
            bundle_identity,
        )
        try:
            existing = _attached_device(
                metadata,
                runner,
                bundle_identity=bundle_identity,
            )
        except ArchiveVolumeRefusedError as exc:
            raise _refused() from exc
        if existing is not None:
            if require_fresh_attach:
                raise _refused()
            try:
                validated_device, volume_uuid, filesystem_capacity = _validate_attached_volume(
                    metadata,
                    runner,
                    parent_descriptor,
                    bundle_identity,
                )
                if validated_device != existing:
                    raise _refused()
                return _Attachment(
                    validated_device,
                    volume_uuid,
                    filesystem_capacity,
                    None,
                )
            except ArchiveVolumeRefusedError as exc:
                raise _refused() from exc

        _require_created_bundle_postcondition(
            parent_descriptor,
            metadata,
            bundle_identity,
        )
        try:
            attach_result = _call(
                runner,
                attach_command(metadata),
                _credential_input(credential),
                cwd_fd=parent_descriptor,
            )
        except ArchiveVolumeRefusedError as exc:
            # A command failure cannot prove that no attachment was created.
            raise _refused() from exc
        try:
            detach_authority = _device_from_attach_response(metadata, attach_result.stdout)
        except ArchiveVolumeRefusedError as exc:
            # A successful attach with no provable device is operator recovery.
            raise _refused() from exc
        try:
            _revalidate_external_parent(metadata, runner, parent_descriptor)
            if _require_durable_bundle_binding(parent_descriptor, metadata) != bundle_identity:
                raise _refused()
            validated_device, volume_uuid, filesystem_capacity = _validate_attached_volume(
                metadata,
                runner,
                parent_descriptor,
                bundle_identity,
            )
            if validated_device != detach_authority.device:
                raise _refused()
            return _Attachment(
                validated_device,
                volume_uuid,
                filesystem_capacity,
                detach_authority,
            )
        except ArchiveVolumeRefusedError as exc:
            _detach_exact(runner, detach_authority)
            raise _refused() from exc
    finally:
        if owns_parent_descriptor:
            os.close(parent_descriptor)


def _detach_exact(runner: CommandRunner, authority: _DetachAuthority) -> bool:
    if (
        not isinstance(authority, _DetachAuthority)
        or authority.issuer is not _DETACH_AUTHORITY_ISSUER
    ):
        return False
    try:
        if isinstance(runner, _DefaultCommandRunner):
            result = runner.detach(authority)
            if (
                type(result.returncode) is not int
                or result.returncode != 0
                or not isinstance(result.stdout, bytes)
                or not isinstance(result.stderr, bytes)
                or result.cwd_identity is not None
                or len(result.stdout) > MAX_PLIST_BYTES
                or len(result.stderr) > MAX_PLIST_BYTES
            ):
                return False
        else:
            _call(runner, (HDIUTIL, "detach", authority.device))
    except ArchiveVolumeRefusedError:
        return False
    return True


def _durable_metadata(path: Path) -> ArchiveVolumeMetadata | None:
    try:
        return load_archive_metadata(path)
    except ArchiveVolumeRefusedError:
        return None


def _persist_transition(
    path: Path,
    current: ArchiveVolumeMetadata,
    target: ArchiveVolumeMetadata,
    writer: MetadataWriter,
) -> None:
    if target.generation != current.generation + 1:
        raise _refused()
    expected_bytes = _metadata_bytes(current)
    target_bytes = _metadata_bytes(target)
    with _metadata_lock(path) as parent_descriptor:
        if _read_metadata_bytes(parent_descriptor, path.name) != expected_bytes:
            raise _refused()
        try:
            writer(path, target)
        except Exception as exc:
            raise _refused() from exc
        if _read_metadata_bytes(parent_descriptor, path.name) != target_bytes:
            raise _refused()


def _created_bundle_identity(
    parent_descriptor: int,
    metadata: ArchiveVolumeMetadata,
) -> tuple[int, int]:
    try:
        details = os.stat(
            metadata.bundle_path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise _refused() from exc
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise _refused()
    return details.st_dev, details.st_ino


def _image_metadata_fingerprint(
    parent_descriptor: int,
    metadata: ArchiveVolumeMetadata,
) -> str:
    bundle_descriptor = -1
    image_descriptor = -1
    try:
        bundle_descriptor = os.open(
            metadata.bundle_path.name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        image_descriptor = os.open(
            "Info.plist",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=bundle_descriptor,
        )
        details = os.fstat(image_descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_IMAGE_METADATA_BYTES:
            raise _refused()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(image_descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMAGE_METADATA_BYTES:
                raise _refused()
            chunks.append(chunk)
        raw = b"".join(chunks)
        payload = _parse_plist(raw)
        if not payload:
            raise _refused()
        return hashlib.sha256(raw).hexdigest()
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    finally:
        if image_descriptor >= 0:
            os.close(image_descriptor)
        if bundle_descriptor >= 0:
            os.close(bundle_descriptor)


def _require_durable_bundle_binding(
    parent_descriptor: int,
    metadata: ArchiveVolumeMetadata,
) -> tuple[int, int]:
    if metadata.bundle_inode is None or metadata.image_metadata_sha256 is None:
        raise _refused()
    identity = _created_bundle_identity(parent_descriptor, metadata)
    if identity[1] != metadata.bundle_inode:
        raise _refused()
    if _image_metadata_fingerprint(parent_descriptor, metadata) != metadata.image_metadata_sha256:
        raise _refused()
    return identity


def _require_created_bundle_postcondition(
    parent_descriptor: int,
    metadata: ArchiveVolumeMetadata,
    created_identity: tuple[int, int],
) -> None:
    _revalidate_directory(parent_descriptor, metadata.bundle_path.parent)
    if _created_bundle_identity(parent_descriptor, metadata) != created_identity:
        raise _refused()
    try:
        live = os.stat(metadata.bundle_path, follow_symlinks=False)
    except OSError as exc:
        raise _refused() from exc
    if (live.st_dev, live.st_ino) != created_identity:
        raise _refused()


def provision_archive_volume(
    metadata: ArchiveVolumeMetadata,
    *,
    credential: str,
    expected_channel: str | None = None,
    runner: CommandRunner | None = None,
    metadata_path: Path | None = None,
    metadata_writer: MetadataWriter = write_archive_metadata,
    _descriptor_authority: object | None = None,
) -> ArchiveVolumeReady:
    _require_expected_channel(metadata, expected_channel)
    if metadata_path is not None:
        held: dict[str, int] = getattr(_METADATA_LOCK_STATE, "held", {})
        if str(metadata_path) not in held:
            with _metadata_lock(metadata_path):
                return provision_archive_volume(
                    metadata,
                    credential=credential,
                    expected_channel=expected_channel,
                    runner=runner,
                    metadata_path=metadata_path,
                    metadata_writer=metadata_writer,
                    _descriptor_authority=_descriptor_authority,
                )
    selected = (
        _runner(metadata, descriptor_authority=_descriptor_authority)
        if runner is None
        else runner
    )
    if metadata_path is not None:
        if _durable_metadata(metadata_path) != metadata:
            raise _refused()
        parent_descriptor = getattr(_METADATA_LOCK_STATE, "held", {})[
            str(metadata_path)
        ]
        if _read_metadata_bytes(parent_descriptor, metadata_path.name) != _metadata_bytes(
            metadata
        ):
            raise _refused()

    if metadata.state == BOUND_ACTIVE:
        _require_bundle_directory(metadata)
        _mount_and_validate(metadata, credential=credential, runner=selected)
        return _issue_archive_volume_ready(metadata.archive_id, metadata.mountpoint)

    if metadata_path is None:
        raise _refused()

    if metadata.state in {PROVISIONING_FAILED, ATTACHED_VERIFIED}:
        _require_bundle_directory(metadata)
        attachment = _mount_and_validate(
            metadata,
            credential=credential,
            runner=selected,
            require_fresh_attach=metadata.state == PROVISIONING_FAILED,
        )
        attached = (
            replace(
                metadata,
                generation=metadata.generation + 1,
                state=ATTACHED_VERIFIED,
                volume_uuid=attachment.volume_uuid,
                filesystem_capacity_bytes=attachment.filesystem_capacity_bytes,
            )
            if metadata.state == PROVISIONING_FAILED
            else metadata
        )
        try:
            if metadata.state == PROVISIONING_FAILED:
                _persist_transition(metadata_path, metadata, attached, metadata_writer)
            active = replace(
                attached,
                generation=attached.generation + 1,
                state=BOUND_ACTIVE,
            )
            _persist_transition(metadata_path, attached, active, metadata_writer)
        except ArchiveVolumeRefusedError:
            if attachment.detach_authority is not None:
                _detach_exact(selected, attachment.detach_authority)
            raise
        return _issue_archive_volume_ready(metadata.archive_id, metadata.mountpoint)

    _require_empty_mount_directory(metadata)
    if _attached_device(metadata, selected) is not None:
        raise _refused()
    if os.path.lexists(metadata.bundle_path):
        raise _refused()
    parent = _safe_path(metadata.bundle_path.parent)
    try:
        parent_details = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise _refused() from exc
    if not stat.S_ISDIR(parent_details.st_mode) or stat.S_ISLNK(parent_details.st_mode):
        raise _refused()
    parent_descriptor = _open_external_parent(metadata, selected)
    try:
        _revalidate_directory(parent_descriptor, metadata.bundle_path.parent)
        _call(
            selected,
            create_command(metadata),
            _credential_input(credential),
            cwd_fd=parent_descriptor,
        )
        created_identity = _created_bundle_identity(parent_descriptor, metadata)
        image_fingerprint = _image_metadata_fingerprint(parent_descriptor, metadata)
        residual = replace(
            metadata,
            generation=metadata.generation + 1,
            state=PROVISIONING_FAILED,
            bundle_inode=created_identity[1],
            image_metadata_sha256=image_fingerprint,
        )
        _persist_transition(metadata_path, metadata, residual, metadata_writer)
        _require_created_bundle_postcondition(
            parent_descriptor,
            residual,
            created_identity,
        )
        try:
            attachment = _mount_and_validate(
                residual,
                credential=credential,
                runner=selected,
                parent_descriptor=parent_descriptor,
                bundle_identity=created_identity,
                require_fresh_attach=True,
            )
        except ArchiveVolumeRefusedError:
            raise

        attached = replace(
            residual,
            generation=residual.generation + 1,
            state=ATTACHED_VERIFIED,
            volume_uuid=attachment.volume_uuid,
            filesystem_capacity_bytes=attachment.filesystem_capacity_bytes,
        )
        try:
            _persist_transition(metadata_path, residual, attached, metadata_writer)
        except ArchiveVolumeRefusedError:
            if attachment.detach_authority is not None:
                _detach_exact(selected, attachment.detach_authority)
            raise

        active = replace(
            attached,
            generation=attached.generation + 1,
            state=BOUND_ACTIVE,
        )
        try:
            _persist_transition(metadata_path, attached, active, metadata_writer)
        except ArchiveVolumeRefusedError:
            if attachment.detach_authority is not None:
                _detach_exact(selected, attachment.detach_authority)
            raise
    finally:
        os.close(parent_descriptor)
    return _issue_archive_volume_ready(metadata.archive_id, metadata.mountpoint)


def _bootstrap_credential(
    *,
    expected_channel: str,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    if (
        source.get(HOST_SECRET_BOOTSTRAP_CHANNEL) != expected_channel
        or source.get(HOST_SECRET_BOOTSTRAP_CONSUMER) != "heimdal-cold-volume"
    ):
        raise _refused()
    values = load_runtime_secret_values(source)
    if set(values) != {ARCHIVE_SECRET_BINDING}:
        raise _refused()
    return values[ARCHIVE_SECRET_BINDING]


def provision_from_bootstrap(
    metadata: ArchiveVolumeMetadata,
    *,
    expected_channel: str,
    env: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    metadata_path: Path | None = None,
    metadata_writer: MetadataWriter = write_archive_metadata,
    _descriptor_authority: object | None = None,
) -> ArchiveVolumeReady:
    return provision_archive_volume(
        metadata,
        credential=_bootstrap_credential(
            expected_channel=expected_channel,
            env=env,
        ),
        expected_channel=expected_channel,
        runner=runner,
        metadata_path=metadata_path,
        metadata_writer=metadata_writer,
        _descriptor_authority=_descriptor_authority,
    )


def mount_from_bootstrap(
    metadata: ArchiveVolumeMetadata,
    *,
    expected_channel: str,
    env: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    _descriptor_authority: object | None = None,
) -> ArchiveVolumeReady:
    return mount_archive_volume(
        metadata,
        credential=_bootstrap_credential(
            expected_channel=expected_channel,
            env=env,
        ),
        expected_channel=expected_channel,
        runner=runner,
        _descriptor_authority=_descriptor_authority,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the declared Heimdal cold volume")
    parser.add_argument(
        "action", choices=("initialize", "require-ready", "mount", "provision")
    )
    parser.add_argument("--channel", choices=sorted(_CHANNELS), required=True)
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--archive-id")
    parser.add_argument("--bundle-path", type=Path)
    parser.add_argument("--mountpoint", type=Path)
    parser.add_argument("--parent-volume-uuid")
    parser.add_argument("--capacity-bytes", type=int)
    parser.add_argument("--owner-uid", type=int)
    parser.add_argument("--owner-gid", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "initialize":
            if (
                args.config_root is not None
                or args.metadata is None
                or args.archive_id is None
                or args.bundle_path is None
                or args.mountpoint is None
                or args.parent_volume_uuid is None
                or args.capacity_bytes is None
                or args.owner_uid is None
                or args.owner_gid is None
            ):
                raise _refused()
            parent_details = _require_exact_path_spelling(args.metadata.parent)
            if not stat.S_ISDIR(parent_details.st_mode):
                raise _refused()
            parent_descriptor = os.open(
                args.metadata.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                normalized_name = unicodedata.normalize(
                    "NFC", args.metadata.name
                ).casefold()
                if any(
                    unicodedata.normalize("NFC", entry).casefold()
                    == normalized_name
                    for entry in os.listdir(parent_descriptor)
                ):
                    raise _refused()
            finally:
                os.close(parent_descriptor)
            initial = ArchiveVolumeMetadata(
                generation=0,
                state=PLANNED_UNBOUND,
                channel=args.channel,
                archive_id=args.archive_id,
                bundle_path=args.bundle_path,
                mountpoint=args.mountpoint,
                parent_volume_uuid=args.parent_volume_uuid,
                bundle_inode=None,
                image_metadata_sha256=None,
                volume_uuid=None,
                capacity_bytes=args.capacity_bytes,
                filesystem_capacity_bytes=None,
                owner_uid=args.owner_uid,
                owner_gid=args.owner_gid,
                mode=0o700,
            )
            write_archive_metadata(args.metadata, initial)
            print(
                json.dumps(
                    {"ok": True, "archive_ref": "archive-metadata-initialized"}
                )
            )
            return 0
        if (
            args.config_root is None
            or args.metadata is not None
            or args.archive_id is not None
            or args.bundle_path is not None
            or args.mountpoint is not None
            or args.parent_volume_uuid is not None
            or args.capacity_bytes is not None
            or args.owner_uid is not None
            or args.owner_gid is not None
        ):
            raise _refused()
        metadata_path, metadata = _channel_archive_metadata_authority(
            config_root=args.config_root,
            channel=args.channel,
        )
        if args.action == "require-ready":
            require_archive_volume_ready(
                metadata,
                expected_channel=args.channel,
                _descriptor_authority=_ONE_SHOT_DESCRIPTOR_AUTHORITY,
            )
        elif args.action == "mount":
            mount_from_bootstrap(
                metadata,
                expected_channel=args.channel,
                _descriptor_authority=_ONE_SHOT_DESCRIPTOR_AUTHORITY,
            )
        else:
            provision_from_bootstrap(
                metadata,
                expected_channel=args.channel,
                metadata_path=metadata_path,
                _descriptor_authority=_ONE_SHOT_DESCRIPTOR_AUTHORITY,
            )
    except ArchiveVolumeRefusedError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    print(json.dumps({"ok": True, "archive_ref": "archive-volume-verified"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARCHIVE_SECRET",
    "ARCHIVE_SECRET_BINDING",
    "ATTACHED_VERIFIED",
    "BOUND_ACTIVE",
    "ArchiveVolumeMetadata",
    "ArchiveVolumeReady",
    "ArchiveVolumeRefusedError",
    "CommandResult",
    "HDIUTIL",
    "DISKUTIL",
    "MAX_PLIST_BYTES",
    "PLANNED_UNBOUND",
    "PROVISIONING_FAILED",
    "attach_command",
    "create_command",
    "load_archive_metadata",
    "load_channel_archive_metadata",
    "mount_archive_volume",
    "mount_from_bootstrap",
    "provision_archive_volume",
    "provision_from_bootstrap",
    "require_archive_volume_ready",
    "run_command",
    "validate_command",
    "write_archive_metadata",
]
