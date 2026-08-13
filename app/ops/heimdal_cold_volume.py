"""Fail-closed host boundary for Heimdal's encrypted cold volume (HAR-03).

This module provisions or validates one encrypted APFS sparsebundle.  It never
copies raw evidence, changes retention, or activates a raw representation.
Host commands are closed and machine-readable; callers cannot supply an
arbitrary executable, verb, raw device, parent-volume target, or shell string.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from app.ops.host_secret_bootstrap import (
    load_runtime_secret_values,
    validate_secret_value,
)


HDIUTIL = "/usr/bin/hdiutil"
DISKUTIL = "/usr/sbin/diskutil"
MAX_PLIST_BYTES = 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 60.0
MAX_CAPACITY_BYTES = 2**63 - 512
ARCHIVE_SECRET = "heimdal.archive-pass"
ARCHIVE_SECRET_BINDING = "HEIMDAL_ARCHIVE_PASS"
PLANNED_UNBOUND = "planned-unbound"
ATTACHED_VERIFIED = "attached-verified"
BOUND_ACTIVE = "bound-active"
_METADATA_STATES = frozenset({PLANNED_UNBOUND, ATTACHED_VERIFIED, BOUND_ACTIVE})
_ARCHIVE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_UUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
_DEVICE = re.compile(r"^/dev/disk[0-9][0-9A-Za-z._-]*$")
_DEVICE_IDENTIFIER = re.compile(r"^disk[0-9][0-9A-Za-z._-]*$")
_METADATA_KEYS = frozenset(
    {
        "state",
        "archive_id",
        "bundle_path",
        "mountpoint",
        "volume_uuid",
        "capacity_bytes",
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
        "Encryption",
        "VolumeName",
    }
)
_PARENT_DISK_KEYS = frozenset({"DeviceIdentifier", "MountPoint", "Internal"})


class ArchiveVolumeRefusedError(RuntimeError):
    """A redacted archive-volume refusal."""


@dataclass(frozen=True)
class ArchiveVolumeMetadata:
    state: str
    archive_id: str
    bundle_path: Path
    mountpoint: Path
    volume_uuid: str | None
    capacity_bytes: int
    owner_uid: int
    owner_gid: int
    mode: int

    def __post_init__(self) -> None:
        if (
            type(self.state) is not str
            or self.state not in _METADATA_STATES
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
            or (
                self.state == PLANNED_UNBOUND
                and self.volume_uuid is not None
            )
            or (
                self.state != PLANNED_UNBOUND
                and (
                    type(self.volume_uuid) is not str
                    or _UUID.fullmatch(self.volume_uuid) is None
                )
            )
            or type(self.capacity_bytes) is not int
            or self.capacity_bytes <= 0
            or self.capacity_bytes > MAX_CAPACITY_BYTES
            or self.capacity_bytes % 512 != 0
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


@dataclass(frozen=True)
class ArchiveVolumeReady:
    ready: bool = True
    archive_ref: str = "archive-volume-verified"


CommandRunner = Callable[..., CommandResult]
Executor = Callable[..., subprocess.CompletedProcess[bytes]]
MetadataWriter = Callable[[Path, ArchiveVolumeMetadata], None]


def _refused() -> ArchiveVolumeRefusedError:
    return ArchiveVolumeRefusedError("archive volume is not ready")


def _safe_path(path: Path) -> Path:
    try:
        if path.is_symlink():
            raise _refused()
        return path.resolve(strict=False)
    except OSError as exc:
        raise _refused() from exc


def _path_key(path: Path) -> str:
    return os.path.normcase(str(_safe_path(path))).casefold()


def _metadata_dict(metadata: ArchiveVolumeMetadata) -> dict[str, object]:
    payload = asdict(metadata)
    payload["bundle_path"] = str(metadata.bundle_path)
    payload["mountpoint"] = str(metadata.mountpoint)
    return payload


def write_archive_metadata(path: Path, metadata: ArchiveVolumeMetadata) -> None:
    """Atomically write a closed, value-free metadata document."""
    if not path.is_absolute() or path.is_symlink():
        raise _refused()
    parent = path.parent
    try:
        parent_details = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_details.st_mode) or stat.S_ISLNK(parent_details.st_mode):
            raise _refused()
        if path.exists():
            current = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or stat.S_IMODE(current.st_mode) != 0o600:
                raise _refused()
    except ArchiveVolumeRefusedError:
        raise
    except OSError as exc:
        raise _refused() from exc
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            json.dump(_metadata_dict(metadata), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)
        raise


def load_archive_metadata(path: Path) -> ArchiveVolumeMetadata:
    if not path.is_absolute() or path.is_symlink():
        raise _refused()
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise _refused()
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            payload = json.load(handle)
    except ArchiveVolumeRefusedError:
        raise
    except Exception as exc:
        raise _refused() from exc
    if not isinstance(payload, dict) or set(payload) != _METADATA_KEYS:
        raise _refused()
    try:
        return ArchiveVolumeMetadata(
            state=payload["state"],
            archive_id=payload["archive_id"],
            bundle_path=Path(payload["bundle_path"]),
            mountpoint=Path(payload["mountpoint"]),
            volume_uuid=payload["volume_uuid"],
            capacity_bytes=payload["capacity_bytes"],
            owner_uid=payload["owner_uid"],
            owner_gid=payload["owner_gid"],
            mode=payload["mode"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _refused() from exc


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
        str(metadata.bundle_path),
    )


def validate_command(
    argv: tuple[str, ...],
    metadata: ArchiveVolumeMetadata,
    *,
    cwd_fd: int | None = None,
) -> None:
    allowed = {
        (HDIUTIL, "info", "-plist"),
        (HDIUTIL, "isencrypted", str(metadata.bundle_path), "-plist"),
        attach_command(metadata),
        (DISKUTIL, "info", "-plist", str(metadata.bundle_path.parent)),
    }
    if argv in allowed:
        return
    if argv == create_command(metadata):
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
    if argv[:2] == (HDIUTIL, "detach") and len(argv) == 3:
        if _DEVICE.fullmatch(argv[2]) is not None:
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
) -> CommandResult:
    validate_command(argv, metadata, cwd_fd=cwd_fd)
    cwd_identity: tuple[int, int] | None = None
    extra: dict[str, object] = {}
    if cwd_fd is not None:
        try:
            before = os.fstat(cwd_fd)
        except OSError as exc:
            raise _refused() from exc
        if not stat.S_ISDIR(before.st_mode):
            raise _refused()
        cwd_identity = (before.st_dev, before.st_ino)
        extra = {
            "cwd": f"/dev/fd/{cwd_fd}",
            "pass_fds": (cwd_fd,),
        }
    try:
        completed = executor(
            list(argv),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            env={"PATH": "/usr/bin:/usr/sbin"},
            **extra,
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


def _runner(metadata: ArchiveVolumeMetadata) -> CommandRunner:
    def selected(
        argv: tuple[str, ...],
        stdin: bytes | None = None,
        cwd_fd: int | None = None,
    ) -> CommandResult:
        return run_command(argv, metadata, stdin, cwd_fd)

    return selected


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


def _attached_device(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
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
        image_matches = _path_key(Path(image_path)) == expected_bundle
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
) -> str:
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
    return matches[0]


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
        if (
            type(identifier) is not str
            or _DEVICE_IDENTIFIER.fullmatch(identifier) is None
            or type(mountpoint) is not str
            or not Path(mountpoint).is_absolute()
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


def _require_encrypted(metadata: ArchiveVolumeMetadata, runner: CommandRunner) -> None:
    payload = _parse_plist(
        _call(
            runner,
            (HDIUTIL, "isencrypted", str(metadata.bundle_path), "-plist"),
        ).stdout
    )
    if "encrypted" not in payload or payload["encrypted"] is not True:
        raise _refused()


def _require_disk_info(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    device: str,
) -> str:
    payload = _parse_plist(
        _call(runner, (DISKUTIL, "info", "-plist", device)).stdout
    )
    if not _DISK_KEYS.issubset(payload):
        raise _refused()
    volume_uuid = payload["VolumeUUID"]
    if (
        payload["DeviceIdentifier"] != device.removeprefix("/dev/")
        or payload["MountPoint"] != str(metadata.mountpoint)
        or type(volume_uuid) is not str
        or _UUID.fullmatch(volume_uuid) is None
        or payload["FilesystemType"] != "apfs"
        or type(payload["TotalSize"]) is not int
        or payload["TotalSize"] != metadata.capacity_bytes
        or payload["Internal"] is not False
        or payload["Encryption"] is not True
        or payload["VolumeName"] != metadata.archive_id
    ):
        raise _refused()
    canonical_uuid = volume_uuid.upper()
    if metadata.volume_uuid is not None and canonical_uuid != metadata.volume_uuid.upper():
        raise _refused()
    return canonical_uuid


def require_archive_volume_ready(
    metadata: ArchiveVolumeMetadata,
    *,
    runner: CommandRunner | None = None,
) -> ArchiveVolumeReady:
    if metadata.state != BOUND_ACTIVE:
        raise _refused()
    selected = _runner(metadata) if runner is None else runner
    _validate_attached_volume(metadata, selected)
    return ArchiveVolumeReady()


@dataclass(frozen=True)
class _Attachment:
    device: str
    volume_uuid: str
    attached_here: bool


def _validate_attached_volume(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
) -> tuple[str, str]:
    _require_external_parent(metadata, runner)
    _require_bundle_directory(metadata)
    mount_descriptor = _open_mount_directory(metadata)
    try:
        device = _attached_device(metadata, runner)
        if device is None:
            raise _refused()
        _require_encrypted(metadata, runner)
        volume_uuid = _require_disk_info(metadata, runner, device)
        _revalidate_directory(mount_descriptor, metadata.mountpoint)
        return device, volume_uuid
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
    runner: CommandRunner | None = None,
) -> ArchiveVolumeReady:
    if metadata.state != BOUND_ACTIVE:
        raise _refused()
    selected = _runner(metadata) if runner is None else runner
    _mount_and_validate(metadata, credential=credential, runner=selected)
    return ArchiveVolumeReady()


def _mount_and_validate(
    metadata: ArchiveVolumeMetadata,
    *,
    credential: str,
    runner: CommandRunner,
) -> _Attachment:
    existing = _attached_device(metadata, runner)
    attached_here = existing is None
    device = existing
    if attached_here:
        attach_result = _call(
            runner,
            attach_command(metadata),
            _credential_input(credential),
        )
        device = _device_from_attach_response(metadata, attach_result.stdout)
    try:
        validated_device, volume_uuid = _validate_attached_volume(metadata, runner)
        if validated_device != device:
            raise _refused()
        return _Attachment(validated_device, volume_uuid, attached_here)
    except ArchiveVolumeRefusedError:
        if attached_here and device is not None:
            _detach_exact(runner, device)
        raise


def _detach_exact(runner: CommandRunner, device: str) -> bool:
    try:
        _call(runner, (HDIUTIL, "detach", device))
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
    if _durable_metadata(path) != current:
        raise _refused()
    try:
        writer(path, target)
    except Exception as exc:
        raise _refused() from exc
    if _durable_metadata(path) != target:
        raise _refused()


def _cleanup_created_bundle(
    metadata: ArchiveVolumeMetadata,
    runner: CommandRunner,
    created_identity: tuple[int, int],
    *,
    parent_descriptor: int | None = None,
    parent_identity: tuple[int, int] | None = None,
) -> bool:
    """Delete only the exact bundle created by this live attempt."""
    descriptor = -1
    owns_descriptor = parent_descriptor is None
    try:
        attached = _attached_device(metadata, runner)
        if attached is not None and not _detach_exact(runner, attached):
            return False
        if _attached_device(metadata, runner) is not None:
            return False
        if not shutil.rmtree.avoids_symlink_attacks:
            return False
        if parent_descriptor is None:
            descriptor = os.open(
                metadata.bundle_path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            parent_details = os.fstat(descriptor)
            live_parent = os.stat(metadata.bundle_path.parent, follow_symlinks=False)
            if not os.path.samestat(parent_details, live_parent):
                return False
        else:
            descriptor = parent_descriptor
            parent_details = os.fstat(descriptor)
            if (
                parent_identity is None
                or (parent_details.st_dev, parent_details.st_ino) != parent_identity
            ):
                return False
        details = os.stat(
            metadata.bundle_path.name,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(details.st_mode)
            or stat.S_ISLNK(details.st_mode)
            or (details.st_dev, details.st_ino) != created_identity
        ):
            return False
        shutil.rmtree(metadata.bundle_path.name, dir_fd=descriptor)
        os.fsync(descriptor)
        try:
            os.stat(
                metadata.bundle_path.name,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return True
        return False
    except (ArchiveVolumeRefusedError, OSError):
        return False
    finally:
        if owns_descriptor and descriptor >= 0:
            os.close(descriptor)


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
    runner: CommandRunner | None = None,
    metadata_path: Path | None = None,
    metadata_writer: MetadataWriter = write_archive_metadata,
) -> ArchiveVolumeReady:
    selected = _runner(metadata) if runner is None else runner
    if metadata_path is not None and _durable_metadata(metadata_path) != metadata:
        raise _refused()

    if metadata.state == BOUND_ACTIVE:
        _require_bundle_directory(metadata)
        _mount_and_validate(metadata, credential=credential, runner=selected)
        return ArchiveVolumeReady()

    if metadata_path is None:
        raise _refused()

    if metadata.state == ATTACHED_VERIFIED:
        _require_bundle_directory(metadata)
        attachment = _mount_and_validate(metadata, credential=credential, runner=selected)
        active = replace(metadata, state=BOUND_ACTIVE)
        try:
            _persist_transition(metadata_path, metadata, active, metadata_writer)
        except ArchiveVolumeRefusedError:
            if attachment.attached_here:
                _detach_exact(selected, attachment.device)
            raise
        return ArchiveVolumeReady()

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
        parent_details = os.fstat(parent_descriptor)
        parent_identity = (parent_details.st_dev, parent_details.st_ino)
        _revalidate_directory(parent_descriptor, metadata.bundle_path.parent)
        _call(
            selected,
            create_command(metadata),
            _credential_input(credential),
            cwd_fd=parent_descriptor,
        )
        created_identity = _created_bundle_identity(parent_descriptor, metadata)
        try:
            _require_created_bundle_postcondition(
                parent_descriptor,
                metadata,
                created_identity,
            )
            attachment = _mount_and_validate(
                metadata,
                credential=credential,
                runner=selected,
            )
        except ArchiveVolumeRefusedError:
            _cleanup_created_bundle(
                metadata,
                selected,
                created_identity,
                parent_descriptor=parent_descriptor,
                parent_identity=parent_identity,
            )
            raise

        attached = replace(
            metadata,
            state=ATTACHED_VERIFIED,
            volume_uuid=attachment.volume_uuid,
        )
        try:
            _persist_transition(metadata_path, metadata, attached, metadata_writer)
        except ArchiveVolumeRefusedError:
            if _durable_metadata(metadata_path) != attached:
                _cleanup_created_bundle(
                    metadata,
                    selected,
                    created_identity,
                    parent_descriptor=parent_descriptor,
                    parent_identity=parent_identity,
                )
            raise

        active = replace(attached, state=BOUND_ACTIVE)
        try:
            _persist_transition(metadata_path, attached, active, metadata_writer)
        except ArchiveVolumeRefusedError:
            if attachment.attached_here:
                _detach_exact(selected, attachment.device)
            raise
    finally:
        os.close(parent_descriptor)
    return ArchiveVolumeReady()


def _bootstrap_credential(env: Mapping[str, str] | None = None) -> str:
    values = load_runtime_secret_values(os.environ if env is None else env)
    if set(values) != {ARCHIVE_SECRET_BINDING}:
        raise _refused()
    return values[ARCHIVE_SECRET_BINDING]


def provision_from_bootstrap(
    metadata: ArchiveVolumeMetadata,
    *,
    env: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    metadata_path: Path | None = None,
    metadata_writer: MetadataWriter = write_archive_metadata,
) -> ArchiveVolumeReady:
    return provision_archive_volume(
        metadata,
        credential=_bootstrap_credential(env),
        runner=runner,
        metadata_path=metadata_path,
        metadata_writer=metadata_writer,
    )


def mount_from_bootstrap(
    metadata: ArchiveVolumeMetadata,
    *,
    env: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
) -> ArchiveVolumeReady:
    return mount_archive_volume(
        metadata,
        credential=_bootstrap_credential(env),
        runner=runner,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the declared Heimdal cold volume")
    parser.add_argument("action", choices=("require-ready", "mount", "provision"))
    parser.add_argument("--metadata", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        metadata = load_archive_metadata(args.metadata)
        if args.action == "require-ready":
            require_archive_volume_ready(metadata)
        elif args.action == "mount":
            mount_from_bootstrap(metadata)
        else:
            provision_from_bootstrap(metadata, metadata_path=args.metadata)
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
    "attach_command",
    "create_command",
    "load_archive_metadata",
    "mount_archive_volume",
    "mount_from_bootstrap",
    "provision_archive_volume",
    "provision_from_bootstrap",
    "require_archive_volume_ready",
    "run_command",
    "validate_command",
    "write_archive_metadata",
]
