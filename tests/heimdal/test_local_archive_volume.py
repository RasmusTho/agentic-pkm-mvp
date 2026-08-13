"""HAR-03: encrypted local archive volume boundary (#3849).

Every host command is simulated.  These tests must never attach, create, erase,
partition, or unlock a real disk image or Keychain item.
"""

from __future__ import annotations

import inspect
import json
import multiprocessing
import os
from dataclasses import replace
from pathlib import Path
import plistlib
import sys
import threading

import pytest

from app.ops import heimdal_cold_volume as volume
from app.ops.host_secret_bootstrap import (
    HOST_SECRET_BOOTSTRAP_CHANNEL,
    HOST_SECRET_BOOTSTRAP_CONSUMER,
    HOST_SECRET_RUNTIME_ENV_FILE,
)
from app.ops.host_secret_contract import load_host_secret_contract


pytestmark = pytest.mark.not_pg

_CAPACITY = 8 * 1024**3
_FILESYSTEM_CAPACITY = _CAPACITY - (80 * 512)
_DEVICE = "/dev/disk9s1"
_UUID = "11111111-2222-3333-4444-555555555555"
_PARENT_UUID = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
_PASSPHRASE = "fixture-secret-never-log"


def _metadata(tmp_path: Path) -> volume.ArchiveVolumeMetadata:
    parent = tmp_path / "external-parent"
    parent.mkdir()
    mountpoint = tmp_path / "archive-mount"
    mountpoint.mkdir()
    mountpoint.chmod(0o700)
    metadata = volume.ArchiveVolumeMetadata(
        generation=3,
        state=volume.BOUND_ACTIVE,
        channel="prod",
        archive_id="heimdal-cold-v1",
        bundle_path=parent / "archive.sparsebundle",
        mountpoint=mountpoint,
        parent_volume_uuid=_PARENT_UUID,
        bundle_inode=1,
        image_metadata_sha256="0" * 64,
        volume_uuid=_UUID,
        capacity_bytes=_CAPACITY,
        filesystem_capacity_bytes=_FILESYSTEM_CAPACITY,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
        mode=0o700,
    )
    return metadata


def _planned_metadata(tmp_path: Path) -> volume.ArchiveVolumeMetadata:
    return replace(
        _metadata(tmp_path),
        generation=0,
        state=volume.PLANNED_UNBOUND,
        bundle_inode=None,
        image_metadata_sha256=None,
        volume_uuid=None,
        filesystem_capacity_bytes=None,
    )


def _plist(payload: object) -> bytes:
    return plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)


def _info(metadata: volume.ArchiveVolumeMetadata) -> bytes:
    return _plist(
        {
            "images": [
                {
                    "image-path": str(metadata.bundle_path),
                    "system-entities": [
                        {
                            "dev-entry": _DEVICE,
                            "mount-point": str(metadata.mountpoint),
                        }
                    ],
                }
            ]
        }
    )


def _attach_info(metadata: volume.ArchiveVolumeMetadata) -> bytes:
    return _plist(
        {
            "system-entities": [
                {
                    "dev-entry": _DEVICE,
                    "mount-point": str(metadata.mountpoint),
                }
            ]
        }
    )


def _disk_info(
    metadata: volume.ArchiveVolumeMetadata,
    **overrides: object,
) -> bytes:
    payload: dict[str, object] = {
        "DeviceIdentifier": _DEVICE.removeprefix("/dev/"),
        "MountPoint": str(metadata.mountpoint),
        "VolumeUUID": metadata.volume_uuid or _UUID,
        "VolumeName": metadata.archive_id,
        "FilesystemType": "apfs",
        "TotalSize": metadata.filesystem_capacity_bytes or _FILESYSTEM_CAPACITY,
        "Internal": False,
        # hdiutil proves encryption at the image layer. A newly formatted APFS
        # volume is not implicitly APFS-encrypted by that image operation.
        "Encryption": False,
    }
    payload.update(overrides)
    return _plist(payload)


def _parent_info(
    metadata: volume.ArchiveVolumeMetadata,
    **overrides: object,
) -> bytes:
    payload: dict[str, object] = {
        "DeviceIdentifier": "disk8s1",
        "MountPoint": str(metadata.bundle_path.parent),
        "VolumeUUID": metadata.parent_volume_uuid,
        "Internal": False,
    }
    payload.update(overrides)
    return _plist(payload)


class FakeRunner:
    def __init__(
        self,
        metadata: volume.ArchiveVolumeMetadata,
        *,
        attached: bool = True,
        encrypted: object = True,
        disk_overrides: dict[str, object] | None = None,
        parent_overrides: dict[str, object] | None = None,
        attach_rc: int = 0,
    ) -> None:
        self.metadata = metadata
        self.attached = attached
        self.encrypted = encrypted
        self.disk_overrides = disk_overrides or {}
        self.parent_overrides = parent_overrides or {}
        self.attach_rc = attach_rc
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        stdin: bytes | None = None,
        cwd_fd: int | None = None,
    ) -> volume.CommandResult:
        self.calls.append((argv, stdin))
        if argv == (volume.HDIUTIL, "info", "-plist"):
            return volume.CommandResult(0, _info(self.metadata) if self.attached else _plist({"images": []}))
        if argv == (
            volume.HDIUTIL,
            "isencrypted",
            self.metadata.bundle_path.name,
            "-plist",
        ):
            if cwd_fd is None:
                raise AssertionError("image validation must carry descriptor authority")
            details = os.fstat(cwd_fd)
            return volume.CommandResult(
                0,
                _plist({"encrypted": self.encrypted}),
                cwd_identity=(details.st_dev, details.st_ino),
            )
        if argv == (volume.DISKUTIL, "info", "-plist", _DEVICE):
            return volume.CommandResult(0, _disk_info(self.metadata, **self.disk_overrides))
        if argv == (
            volume.DISKUTIL,
            "info",
            "-plist",
            str(self.metadata.bundle_path.parent),
        ):
            return volume.CommandResult(
                0,
                _parent_info(self.metadata, **self.parent_overrides),
            )
        if argv[:2] == (volume.HDIUTIL, "attach"):
            if cwd_fd is None:
                raise AssertionError("attach must carry descriptor authority")
            details = os.fstat(cwd_fd)
            if self.attach_rc == 0:
                self.attached = True
                self.metadata.mountpoint.chmod(self.metadata.mode)
                return volume.CommandResult(
                    0,
                    _attach_info(self.metadata),
                    cwd_identity=(details.st_dev, details.st_ino),
                )
            return volume.CommandResult(self.attach_rc, b"", b"fixture-private-detail")
        if argv[:2] == (volume.HDIUTIL, "create"):
            if cwd_fd is None:
                raise AssertionError("create must carry descriptor-bound authority")
            details = os.fstat(cwd_fd)
            os.mkdir(self.metadata.bundle_path.name, dir_fd=cwd_fd)
            bundle_descriptor = os.open(
                self.metadata.bundle_path.name,
                os.O_RDONLY,
                dir_fd=cwd_fd,
            )
            try:
                image_descriptor = os.open(
                    "Info.plist",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=bundle_descriptor,
                )
                try:
                    os.write(
                        image_descriptor,
                        _plist({"fixture-image-id": self.metadata.archive_id}),
                    )
                finally:
                    os.close(image_descriptor)
            finally:
                os.close(bundle_descriptor)
            return volume.CommandResult(
                0,
                _plist({}),
                cwd_identity=(details.st_dev, details.st_ino),
            )
        if argv == (volume.HDIUTIL, "detach", _DEVICE):
            self.attached = False
            return volume.CommandResult(0, b"")
        raise AssertionError(f"unexpected command shape: {argv!r}")


def _stale_transition_worker(
    metadata_path: Path,
    current: volume.ArchiveVolumeMetadata,
    target: volume.ArchiveVolumeMetadata,
    start: multiprocessing.synchronize.Barrier,
    results: multiprocessing.queues.Queue,
) -> None:
    """Race the same expected generation in two independent processes."""
    start.wait(timeout=10)
    try:
        volume._persist_transition(
            metadata_path,
            current,
            target,
            volume.write_archive_metadata,
        )
    except volume.ArchiveVolumeRefusedError:
        results.put("refused")
    else:
        results.put("committed")


def _materialize_ready_fs(metadata: volume.ArchiveVolumeMetadata) -> None:
    metadata.bundle_path.mkdir(exist_ok=True)
    (metadata.bundle_path / "Info.plist").write_bytes(
        _plist({"fixture-image-id": metadata.archive_id})
    )
    metadata.mountpoint.chmod(metadata.mode)
    details = metadata.bundle_path.stat()
    parent_descriptor = os.open(metadata.bundle_path.parent, os.O_RDONLY)
    try:
        fingerprint = volume._image_metadata_fingerprint(parent_descriptor, metadata)
    finally:
        os.close(parent_descriptor)
    object.__setattr__(metadata, "bundle_inode", details.st_ino)
    object.__setattr__(metadata, "image_metadata_sha256", fingerprint)


@pytest.mark.parametrize(
    ("state", "overrides"),
    [
        pytest.param("absent", {}, id="absent"),
        pytest.param("locked", {}, id="locked"),
        pytest.param("unencrypted", {}, id="unencrypted"),
        pytest.param("identity-mismatch", {"VolumeUUID": "different"}, id="identity-mismatch"),
        pytest.param("wrong-owner", {}, id="wrong-owner"),
        pytest.param("wrong-group", {}, id="wrong-group"),
        pytest.param("wrong-mode", {}, id="wrong-mode"),
    ],
)
def test_archive_requires_mounted_encrypted_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    overrides: dict[str, object],
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    runner = FakeRunner(
        metadata,
        attached=state not in {"absent", "locked"},
        encrypted=state != "unencrypted",
        disk_overrides=overrides,
    )
    if state in {"wrong-owner", "wrong-group", "wrong-mode"}:
        real_fstat = os.fstat
        target = os.stat(metadata.mountpoint)

        def wrong_descriptor_owner(descriptor: int) -> os.stat_result:
            result = real_fstat(descriptor)
            if (result.st_dev, result.st_ino) != (target.st_dev, target.st_ino):
                return result
            fields = list(result)
            if state == "wrong-owner":
                fields[4] = result.st_uid + 1
            elif state == "wrong-group":
                fields[5] = result.st_gid + 1
            else:
                fields[0] = (result.st_mode & ~0o777) | 0o750
            return os.stat_result(fields)

        monkeypatch.setattr(volume.os, "fstat", wrong_descriptor_owner)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=runner)


def test_provisioner_never_reformats_or_uses_parent_volume(tmp_path: Path) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    runner = FakeRunner(metadata, attached=False)

    result = volume.provision_archive_volume(
        metadata,
        credential=_PASSPHRASE,
        runner=runner,
        metadata_path=metadata_path,
    )
    assert result.ready is True
    bound = volume.load_archive_metadata(metadata_path)
    assert bound.state == volume.BOUND_ACTIVE
    assert bound.volume_uuid == _UUID
    assert bound.filesystem_capacity_bytes == _FILESYSTEM_CAPACITY
    assert bound.generation == 3

    flattened = [part for argv, _stdin in runner.calls for part in argv]
    forbidden = {"eraseDisk", "partitionDisk", "eraseVolume", "reformat", "-srcdevice", "-ov"}
    assert forbidden.isdisjoint(flattened)
    create = next(argv for argv, _stdin in runner.calls if argv[:2] == (volume.HDIUTIL, "create"))
    assert create == volume.create_command(metadata)
    assert create[create.index("-sectors") + 1] == str(_CAPACITY // 512)
    assert "-size" not in create
    assert str(metadata.bundle_path.parent) not in create
    assert create[-1] == metadata.bundle_path.name
    assert str(metadata.bundle_path) not in create
    assert all(_PASSPHRASE not in part for part in flattened)
    secret_inputs = [stdin for _argv, stdin in runner.calls if stdin is not None]
    assert secret_inputs == [(_PASSPHRASE + "\0").encode(), (_PASSPHRASE + "\0").encode()]


def test_image_encryption_and_filesystem_capacity_are_separate_layers(
    tmp_path: Path,
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)

    # APFS is valid even when diskutil reports that the filesystem layer is
    # unencrypted: hdiutil isencrypted is the AES image-layer authority.
    assert volume.require_archive_volume_ready(
        metadata,
        runner=FakeRunner(metadata, encrypted=True, disk_overrides={"Encryption": False}),
    ).ready
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(
            metadata,
            runner=FakeRunner(metadata, encrypted=False, disk_overrides={"Encryption": True}),
        )

    # hdiutil documents that filesystem/layout overhead is unavailable to the
    # mounted filesystem. Persist and later require the first verified size.
    assert metadata.filesystem_capacity_bytes == _FILESYSTEM_CAPACITY
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(
            metadata,
            runner=FakeRunner(
                metadata,
                disk_overrides={"TotalSize": _FILESYSTEM_CAPACITY - 512},
            ),
        )


def test_mount_credential_is_keychain_backed_and_redacted(tmp_path: Path) -> None:
    contract = load_host_secret_contract()
    contract.require_declared(
        channel="prod",
        consumer="heimdal-cold-volume",
        secret="heimdal.archive-pass",
    )
    binding = contract.binding_for("heimdal.archive-pass")
    assert binding == "HEIMDAL_ARCHIVE_PASS"

    tracked = [
        Path("config/secrets/host_secret_contract.json"),
        Path("docs/HEIMDAL_LOCAL_ARCHIVE/PROVISION_ENCRYPTED_COLD_VOLUME.md"),
        Path("scripts/prod/start_midgard_stack.sh"),
        Path("scripts/deploy_channel.sh"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tracked)
    assert _PASSPHRASE not in combined
    assert "HEIMDAL_ARCHIVE_PASS=" not in combined

    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    secret_file = tmp_path / "secret.env"
    secret_file.write_text(f"{binding}={_PASSPHRASE}\n", encoding="utf-8")
    secret_file.chmod(0o600)
    runner = FakeRunner(metadata, attached=False)
    result = volume.provision_from_bootstrap(
        metadata,
        expected_channel="prod",
        env={
            HOST_SECRET_RUNTIME_ENV_FILE: str(secret_file),
            HOST_SECRET_BOOTSTRAP_CHANNEL: "prod",
            HOST_SECRET_BOOTSTRAP_CONSUMER: "heimdal-cold-volume",
        },
        runner=runner,
        metadata_path=metadata_path,
    )
    assert result.ready is True
    assert _PASSPHRASE not in repr(result)
    assert all(_PASSPHRASE not in " ".join(argv) for argv, _stdin in runner.calls)


@pytest.mark.parametrize(
    ("bootstrap_channel", "bootstrap_consumer"),
    [
        pytest.param("dev", "heimdal-cold-volume", id="wrong-channel"),
        pytest.param("prod", "different-consumer", id="wrong-consumer"),
    ],
)
def test_bootstrap_channel_authority_refuses_before_secret_or_host_use(
    tmp_path: Path,
    bootstrap_channel: str,
    bootstrap_consumer: str,
) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    secret_file = tmp_path / "secret.env"
    secret_file.write_text(
        f"{volume.ARCHIVE_SECRET_BINDING}={_PASSPHRASE}\n",
        encoding="utf-8",
    )
    secret_file.chmod(0o600)
    runner = FakeRunner(metadata, attached=False)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_from_bootstrap(
            metadata,
            expected_channel="prod",
            env={
                HOST_SECRET_RUNTIME_ENV_FILE: str(secret_file),
                HOST_SECRET_BOOTSTRAP_CHANNEL: bootstrap_channel,
                HOST_SECRET_BOOTSTRAP_CONSUMER: bootstrap_consumer,
            },
            runner=runner,
            metadata_path=metadata_path,
        )

    assert runner.calls == []
    assert volume.load_archive_metadata(metadata_path) == metadata


def test_partial_attach_failure_cleans_only_new_attachment(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    runner = FakeRunner(
        metadata,
        attached=False,
        disk_overrides={"VolumeUUID": "different"},
    )

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.mount_archive_volume(metadata, credential=_PASSPHRASE, runner=runner)

    assert (volume.HDIUTIL, "detach", _DEVICE) in [argv for argv, _stdin in runner.calls]

    preexisting = FakeRunner(
        metadata,
        attached=True,
        disk_overrides={"VolumeUUID": "different"},
    )
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.mount_archive_volume(metadata, credential=_PASSPHRASE, runner=preexisting)
    assert not any(argv[:2] == (volume.HDIUTIL, "detach") for argv, _ in preexisting.calls)


@pytest.mark.parametrize("detach_rc", [0, 1])
def test_attach_response_establishes_compensation_before_rediscovery(
    tmp_path: Path,
    detach_rc: int,
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)

    class RediscoveryFailureRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__(metadata, attached=False)
            self.info_calls = 0

        def __call__(
            self,
            argv: tuple[str, ...],
            stdin: bytes | None = None,
            cwd_fd: int | None = None,
        ) -> volume.CommandResult:
            if argv == (volume.HDIUTIL, "info", "-plist"):
                self.calls.append((argv, stdin))
                self.info_calls += 1
                if self.info_calls == 1:
                    return volume.CommandResult(0, _plist({"images": []}))
                return volume.CommandResult(0, _plist({}))
            if argv[:2] == (volume.HDIUTIL, "attach"):
                self.calls.append((argv, stdin))
                if cwd_fd is None:
                    raise AssertionError("attach must carry descriptor authority")
                self.attached = True
                details = os.fstat(cwd_fd)
                return volume.CommandResult(
                    0,
                    _attach_info(metadata),
                    cwd_identity=(details.st_dev, details.st_ino),
                )
            if argv == (volume.HDIUTIL, "detach", _DEVICE):
                self.calls.append((argv, stdin))
                if detach_rc == 0:
                    self.attached = False
                return volume.CommandResult(detach_rc, b"", b"fixture-private-detail")
            return super().__call__(argv, stdin, cwd_fd)

    runner = RediscoveryFailureRunner()
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.mount_archive_volume(metadata, credential=_PASSPHRASE, runner=runner)

    assert (volume.HDIUTIL, "detach", _DEVICE) in [argv for argv, _ in runner.calls]
    assert runner.attached is (detach_rc != 0)


def test_create_is_descriptor_relative_across_parent_path_swap(tmp_path: Path) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    original_parent = metadata.bundle_path.parent
    displaced_parent = tmp_path / "displaced-external-parent"

    class ParentSwapRunner(FakeRunner):
        create_cwd_identity: tuple[int, int] | None = None

        def __call__(
            self,
            argv: tuple[str, ...],
            stdin: bytes | None = None,
            cwd_fd: int | None = None,
            ) -> volume.CommandResult:
                if argv[:2] != (volume.HDIUTIL, "create"):
                    return super().__call__(argv, stdin, cwd_fd)
                result = super().__call__(argv, stdin, cwd_fd)
                original_parent.rename(displaced_parent)
                original_parent.mkdir()
                assert cwd_fd is not None
                held = os.fstat(cwd_fd)
                self.create_cwd_identity = (held.st_dev, held.st_ino)
                return result

    runner = ParentSwapRunner(metadata, attached=False)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert runner.create_cwd_identity is not None
    assert (displaced_parent / metadata.bundle_path.name).exists()
    assert not metadata.bundle_path.exists()
    assert volume.load_archive_metadata(metadata_path).state == volume.PROVISIONING_FAILED


def test_attach_refuses_bundle_swap_and_detaches_only_attempt_device(tmp_path: Path) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    original_parent = metadata.bundle_path.parent
    displaced_parent = tmp_path / "displaced-external-parent"

    class AttachSwapRunner(FakeRunner):
        def __call__(
            self,
            argv: tuple[str, ...],
            stdin: bytes | None = None,
            cwd_fd: int | None = None,
        ) -> volume.CommandResult:
            result = super().__call__(argv, stdin, cwd_fd)
            if argv[:2] == (volume.HDIUTIL, "attach"):
                original_parent.rename(displaced_parent)
                original_parent.mkdir()
                metadata.bundle_path.mkdir()
            return result

    runner = AttachSwapRunner(metadata, attached=False)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert (volume.HDIUTIL, "detach", _DEVICE) in [argv for argv, _ in runner.calls]
    assert (displaced_parent / metadata.bundle_path.name).exists()
    assert metadata.bundle_path.exists()
    assert volume.load_archive_metadata(metadata_path).state == volume.PROVISIONING_FAILED


def test_partial_failure_never_auto_deletes_a_bundle_path() -> None:
    source = inspect.getsource(volume.provision_archive_volume)
    assert "shutil.rmtree" not in source
    assert "os.rmdir" not in source
    assert ".unlink(" not in source


def test_ready_refuses_stale_attachment_after_bundle_replacement(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    original = tmp_path / "original-attached.sparsebundle"
    metadata.bundle_path.rename(original)
    metadata.bundle_path.mkdir()
    (metadata.bundle_path / "Info.plist").write_bytes(
        _plist({"fixture-image-id": metadata.archive_id})
    )
    runner = FakeRunner(metadata, attached=True)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=runner)

    assert original.exists()
    assert metadata.bundle_path.exists()


def test_ready_refuses_casefold_colliding_foreign_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image-path spelling never substitutes for the reported bundle inode."""
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    reported = metadata.bundle_path.with_name(metadata.bundle_path.name.upper())
    assert str(reported).casefold() == str(metadata.bundle_path).casefold()
    expected = metadata.bundle_path.stat()
    monkeypatch.setattr(
        volume,
        "_reported_bundle_identity",
        lambda _path: (expected.st_dev, expected.st_ino + 1),
    )

    class CollisionRunner(FakeRunner):
        def __call__(
            self,
            argv: tuple[str, ...],
            stdin: bytes | None = None,
            cwd_fd: int | None = None,
        ) -> volume.CommandResult:
            if argv == (volume.HDIUTIL, "info", "-plist"):
                return volume.CommandResult(
                    0,
                    _plist(
                        {
                            "images": [
                                {
                                    "image-path": str(reported),
                                    "system-entities": [
                                        {
                                            "dev-entry": _DEVICE,
                                            "mount-point": str(metadata.mountpoint),
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                )
            return super().__call__(argv, stdin, cwd_fd)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=CollisionRunner(metadata))


def test_reported_bundle_identity_refuses_symlink(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    alias = tmp_path / "reported.sparsebundle"
    alias.symlink_to(metadata.bundle_path, target_is_directory=True)

    assert volume._reported_bundle_identity(alias) is None


def test_reported_bundle_identity_observes_replacement_at_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    expected_details = metadata.bundle_path.stat()
    expected = (expected_details.st_dev, expected_details.st_ino)
    displaced = metadata.bundle_path.with_name("displaced.sparsebundle")
    real_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and path == metadata.bundle_path.name and dir_fd is not None:
            swapped = True
            metadata.bundle_path.rename(displaced)
            metadata.bundle_path.mkdir()
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(volume.os, "open", swapping_open)
    observed = volume._reported_bundle_identity(metadata.bundle_path)

    assert swapped is True
    assert observed is not None and observed != expected
    assert displaced.exists()
    assert metadata.bundle_path.exists()


def test_reported_bundle_identity_accepts_alternate_spelling_of_same_inode(
    tmp_path: Path,
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    detour = metadata.bundle_path.parent / "detour"
    detour.mkdir()
    reported = detour / ".." / metadata.bundle_path.name
    expected = metadata.bundle_path.stat()

    assert str(reported) != str(metadata.bundle_path)
    assert volume._reported_bundle_identity(reported) == (
        expected.st_dev,
        expected.st_ino,
    )


def test_ready_refuses_image_metadata_fingerprint_drift(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    (metadata.bundle_path / "Info.plist").write_bytes(
        _plist({"fixture-image-id": "replacement"})
    )

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=FakeRunner(metadata, attached=True))


def test_idempotent_replay_never_overwrites_or_reattaches(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    runner = FakeRunner(metadata, attached=True)

    first = volume.provision_archive_volume(metadata, credential=_PASSPHRASE, runner=runner)
    second = volume.provision_archive_volume(metadata, credential=_PASSPHRASE, runner=runner)
    assert first.ready and second.ready
    assert not any(argv[:2] == (volume.HDIUTIL, "create") for argv, _ in runner.calls)
    assert not any(argv[:2] == (volume.HDIUTIL, "attach") for argv, _ in runner.calls)


@pytest.mark.parametrize(
    "disk_override",
    [
        pytest.param({"MountPoint": "/unexpected"}, id="mount-mismatch"),
        pytest.param({"DeviceIdentifier": "other"}, id="device-mismatch"),
        pytest.param({"Internal": True}, id="internal-media"),
        pytest.param({"FilesystemType": "hfs"}, id="wrong-filesystem"),
        pytest.param({"TotalSize": _CAPACITY + 1}, id="capacity-overflow"),
        pytest.param({"TotalSize": 0}, id="capacity-underflow"),
    ],
)
def test_typed_plist_mismatch_fails_closed(
    tmp_path: Path,
    disk_override: dict[str, object],
) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    runner = FakeRunner(metadata, disk_overrides=disk_override)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=runner)


@pytest.mark.parametrize(
    "parent_override",
    [
        pytest.param({"Internal": True}, id="internal-parent"),
        pytest.param({"Internal": "false"}, id="parent-internal-wrong-type"),
        pytest.param({"MountPoint": "/unexpected"}, id="parent-mount-mismatch"),
        pytest.param({"DeviceIdentifier": 7}, id="parent-device-wrong-type"),
        pytest.param({"VolumeUUID": _UUID}, id="parent-uuid-drift"),
        pytest.param({"VolumeUUID": 7}, id="parent-uuid-wrong-type"),
    ],
)
def test_external_parent_identity_fails_closed_before_create(
    tmp_path: Path,
    parent_override: dict[str, object],
) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    runner = FakeRunner(metadata, attached=False, parent_overrides=parent_override)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert not metadata.bundle_path.exists()
    assert not any(argv[:2] == (volume.HDIUTIL, "create") for argv, _ in runner.calls)


def test_external_parent_rejects_child_directory_and_symlink(tmp_path: Path) -> None:
    child_metadata = _planned_metadata(tmp_path)
    child_path = tmp_path / "child-metadata.json"
    volume.write_archive_metadata(child_path, child_metadata)
    child_runner = FakeRunner(
        child_metadata,
        attached=False,
        parent_overrides={"MountPoint": str(tmp_path)},
    )
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            child_metadata,
            credential=_PASSPHRASE,
            runner=child_runner,
            metadata_path=child_path,
        )

    symlink_parent = tmp_path / "external-link"
    symlink_parent.symlink_to(child_metadata.bundle_path.parent, target_is_directory=True)
    symlink_metadata = replace(
        child_metadata,
        bundle_path=symlink_parent / "archive.sparsebundle",
    )
    symlink_path = tmp_path / "symlink-metadata.json"
    volume.write_archive_metadata(symlink_path, symlink_metadata)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            symlink_metadata,
            credential=_PASSPHRASE,
            runner=FakeRunner(symlink_metadata, attached=False),
            metadata_path=symlink_path,
        )


@pytest.mark.parametrize(
    "capacity",
    [
        pytest.param(0, id="zero"),
        pytest.param(513, id="unaligned"),
        pytest.param(volume.MAX_CAPACITY_BYTES + 512, id="overflow"),
        pytest.param(True, id="boolean"),
        pytest.param("1024", id="wrong-type"),
    ],
)
def test_capacity_metadata_refuses_unrepresentable_sector_count(
    tmp_path: Path,
    capacity: object,
) -> None:
    metadata = _metadata(tmp_path)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        replace(metadata, capacity_bytes=capacity)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"not-a-plist", id="malformed"),
        pytest.param(_plist({}), id="missing-keys"),
        pytest.param(_plist({"images": "wrong"}), id="wrong-type"),
        pytest.param(b"x" * (volume.MAX_PLIST_BYTES + 1), id="oversized"),
    ],
)
def test_malformed_or_oversized_plist_fails_closed(tmp_path: Path, payload: bytes) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)

    def runner(argv: tuple[str, ...], stdin: bytes | None = None) -> volume.CommandResult:
        del stdin
        if argv == (volume.HDIUTIL, "info", "-plist"):
            return volume.CommandResult(0, payload)
        raise AssertionError("command sequence must stop after malformed output")

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=runner)


def test_duplicate_image_match_and_symlink_mountpoint_fail_closed(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _materialize_ready_fs(metadata)
    duplicate = _plist(
        {
            "images": [
                {"image-path": str(metadata.bundle_path), "system-entities": []},
                {"image-path": str(metadata.bundle_path), "system-entities": []},
            ]
        }
    )

    def duplicate_runner(
        argv: tuple[str, ...], stdin: bytes | None = None
    ) -> volume.CommandResult:
        del stdin
        assert argv == (volume.HDIUTIL, "info", "-plist")
        return volume.CommandResult(0, duplicate)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=duplicate_runner)

    metadata.mountpoint.rmdir()
    real_target = tmp_path / "other"
    real_target.mkdir()
    metadata.mountpoint.symlink_to(real_target, target_is_directory=True)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(metadata, runner=FakeRunner(metadata))


def test_command_adapter_is_allowlisted_bounded_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = _metadata(tmp_path)
    for forbidden in (
        (volume.DISKUTIL, "eraseDisk", _DEVICE),
        (volume.DISKUTIL, "partitionDisk", _DEVICE),
        (volume.HDIUTIL, "create", "-ov", str(metadata.bundle_path)),
        ("sh", "-c", "echo unsafe"),
    ):
        with pytest.raises(volume.ArchiveVolumeRefusedError):
            volume.validate_command(forbidden, metadata)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.validate_command(volume.create_command(metadata), metadata)

    detach_executed = False

    def detach_executor(*_args: object, **_kwargs: object):
        nonlocal detach_executed
        detach_executed = True
        raise AssertionError("generic command adapter must not execute detach")

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.run_command(
            (volume.HDIUTIL, "detach", _DEVICE),
            metadata,
            executor=detach_executor,
        )
    assert detach_executed is False

    signature = inspect.signature(volume.run_command)
    assert "shell" not in signature.parameters
    assert "timeout_seconds" in signature.parameters

    def timeout_runner(*_args: object, **_kwargs: object):
        raise TimeoutError("fixture-private-timeout-detail")

    with pytest.raises(volume.ArchiveVolumeRefusedError) as error:
        volume.run_command((volume.HDIUTIL, "info", "-plist"), metadata, executor=timeout_runner)
    assert "fixture-private-timeout-detail" not in str(error.value)

    captured: dict[str, object] = {}

    def descriptor_executor(argv: list[str], **kwargs: object):
        captured["argv"] = argv
        captured.update(kwargs)
        return volume.subprocess.CompletedProcess(argv, 0, _plist({}), b"")

    # This adapter assertion injects a harmless executor and never forks. Keep it
    # independent of unrelated background threads started elsewhere in the suite;
    # the real subprocess contract is exercised in a fresh one-shot process below.
    monkeypatch.setattr(volume.threading, "active_count", lambda: 1)
    parent_descriptor = os.open(metadata.bundle_path.parent, os.O_RDONLY)
    try:
        with pytest.raises(volume.ArchiveVolumeRefusedError):
            volume.run_command(
                volume.create_command(metadata),
                metadata,
                _PASSPHRASE.encode(),
                parent_descriptor,
                executor=descriptor_executor,
            )
        assert captured == {}
        result = volume.run_command(
            volume.create_command(metadata),
            metadata,
            _PASSPHRASE.encode(),
            parent_descriptor,
            executor=descriptor_executor,
            _descriptor_authority=volume._ONE_SHOT_DESCRIPTOR_AUTHORITY,
        )
        details = os.fstat(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    assert "cwd" not in captured
    assert captured["pass_fds"] == (parent_descriptor,)
    assert callable(captured["preexec_fn"])
    assert captured["argv"][-1] == metadata.bundle_path.name
    assert result.cwd_identity == (details.st_dev, details.st_ino)


def test_descriptor_child_executes_in_held_parent_after_path_swap(tmp_path: Path) -> None:
    parent = tmp_path / "external-parent"
    parent.mkdir()
    displaced = tmp_path / "displaced-external-parent"
    proof = """
import os
import sys
from pathlib import Path

from app.ops import heimdal_cold_volume as volume

parent = Path(sys.argv[1])
displaced = Path(sys.argv[2])
descriptor = os.open(parent, os.O_RDONLY)
try:
    before = os.fstat(descriptor)
    parent.rename(displaced)
    parent.mkdir()
    completed = volume._run_closed_child(
        ("/usr/bin/touch", "descriptor-child-marker"),
        stdin=None,
        timeout_seconds=5.0,
        executor=volume.subprocess.run,
        cwd_fd=descriptor,
    )
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)

if completed.returncode != 0 or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
    raise SystemExit(1)
"""
    completed = volume.subprocess.run(
        [sys.executable, "-c", proof, str(parent), str(displaced)],
        stdout=volume.subprocess.PIPE,
        stderr=volume.subprocess.PIPE,
        check=False,
        timeout=10.0,
    )

    assert completed.returncode == 0
    assert (displaced / "descriptor-child-marker").is_file()
    assert not (parent / "descriptor-child-marker").exists()


def test_descriptor_child_refuses_threaded_runtime(tmp_path: Path) -> None:
    descriptor = os.open(tmp_path, os.O_RDONLY)
    errors: list[Exception] = []

    def invoke_from_thread() -> None:
        try:
            volume._run_closed_child(
                ("/usr/bin/true",),
                stdin=None,
                timeout_seconds=5.0,
                executor=volume.subprocess.run,
                cwd_fd=descriptor,
            )
        except Exception as exc:
            errors.append(exc)

    try:
        worker = threading.Thread(target=invoke_from_thread)
        worker.start()
        worker.join(timeout=5)
    finally:
        os.close(descriptor)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], volume.ArchiveVolumeRefusedError)


def test_metadata_is_closed_value_free_and_atomic(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(path, metadata)
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".archive-metadata.json.*")) == [
        tmp_path / ".archive-metadata.json.lock"
    ]
    assert volume.load_archive_metadata(path) == metadata
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.write_archive_metadata(path, metadata)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["credential"] = _PASSPHRASE
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.load_archive_metadata(path)


def test_metadata_transition_is_cross_process_compare_and_swap(tmp_path: Path) -> None:
    planned = _planned_metadata(tmp_path)
    _materialize_ready_fs(planned)
    current = replace(
        planned,
        generation=1,
        state=volume.PROVISIONING_FAILED,
    )
    path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(path, current)
    target_a = replace(
        current,
        generation=2,
        state=volume.ATTACHED_VERIFIED,
        volume_uuid="11111111-2222-3333-4444-555555555555",
        filesystem_capacity_bytes=_FILESYSTEM_CAPACITY,
    )
    target_b = replace(
        target_a,
        volume_uuid="66666666-7777-8888-9999-AAAAAAAAAAAA",
    )

    context = multiprocessing.get_context("fork")
    start = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(
            target=_stale_transition_worker,
            args=(path, current, target, start, results),
        )
        for target in (target_a, target_b)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)

    assert all(not worker.is_alive() and worker.exitcode == 0 for worker in workers)
    outcomes = sorted(results.get(timeout=5) for _worker in workers)
    assert outcomes == ["committed", "refused"]
    assert volume.load_archive_metadata(path) in {target_a, target_b}
    lock_path = path.with_name(f".{path.name}.lock")
    assert lock_path.is_file()
    assert lock_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"state": volume.PLANNED_UNBOUND, "volume_uuid": _UUID},
            id="planned-with-volume-identity",
        ),
        pytest.param(
            {"state": volume.PLANNED_UNBOUND, "bundle_inode": 7},
            id="planned-with-bundle-identity",
        ),
        pytest.param(
            {"state": volume.PLANNED_UNBOUND, "generation": 1},
            id="planned-with-transition-generation",
        ),
        pytest.param(
            {
                "state": volume.PROVISIONING_FAILED,
                "volume_uuid": None,
                "bundle_inode": None,
            },
            id="failed-without-bundle-identity",
        ),
        pytest.param(
            {"state": volume.ATTACHED_VERIFIED, "volume_uuid": None},
            id="attached-without-volume-identity",
        ),
        pytest.param(
            {"state": volume.ATTACHED_VERIFIED, "filesystem_capacity_bytes": None},
            id="attached-without-filesystem-capacity",
        ),
        pytest.param(
            {"state": volume.BOUND_ACTIVE, "volume_uuid": None},
            id="active-without-volume-identity",
        ),
        pytest.param({"parent_volume_uuid": "different"}, id="bad-parent-uuid"),
        pytest.param({"image_metadata_sha256": "short"}, id="bad-image-fingerprint"),
        pytest.param({"generation": -1}, id="negative-generation"),
    ],
)
def test_metadata_state_and_identity_are_coherent(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    metadata = _metadata(tmp_path)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        replace(metadata, **overrides)


def test_channel_authority_rejects_cross_channel_legacy_and_path_override(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "repo"
    config_root.mkdir()
    metadata_path = tmp_path / "prod-archive-metadata.json"
    metadata = _metadata(tmp_path)
    volume.write_archive_metadata(metadata_path, metadata)
    channel_config = config_root / ".env.prod.local"
    channel_config.write_text(
        f"HEIMDAL_ARCHIVE_METADATA_FILE={metadata_path}\n", encoding="utf-8"
    )

    assert volume.load_channel_archive_metadata(
        config_root=config_root,
        channel="prod",
        env={},
    ) == metadata
    assert volume.load_channel_archive_metadata(
        config_root=config_root,
        channel="prod",
        env={"HEIMDAL_ARCHIVE_METADATA_FILE": str(metadata_path)},
    ) == metadata

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.load_channel_archive_metadata(
            config_root=config_root,
            channel="prod",
            env={"HEIMDAL_ARCHIVE_METADATA_FILE": f"{metadata_path.parent}/./{metadata_path.name}"},
        )

    dev_metadata_path = tmp_path / "dev-archive-metadata.json"
    dev_metadata = replace(metadata, channel="dev")
    volume.write_archive_metadata(dev_metadata_path, dev_metadata)
    channel_config.write_text(
        f"HEIMDAL_ARCHIVE_METADATA_FILE={dev_metadata_path}\n", encoding="utf-8"
    )
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.load_channel_archive_metadata(
            config_root=config_root,
            channel="prod",
            env={},
        )

    legacy_path = tmp_path / "legacy-archive-metadata.json"
    legacy_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    legacy_payload.pop("channel")
    legacy_path.write_text(json.dumps(legacy_payload) + "\n", encoding="utf-8")
    legacy_path.chmod(0o600)
    channel_config.write_text(
        f"HEIMDAL_ARCHIVE_METADATA_FILE={legacy_path}\n", encoding="utf-8"
    )
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.load_channel_archive_metadata(
            config_root=config_root,
            channel="prod",
            env={},
        )

    channel_config.write_text(
        f"HEIMDAL_ARCHIVE_METADATA_FILE={metadata_path}\n", encoding="utf-8"
    )
    refusing_runner = FakeRunner(metadata)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.require_archive_volume_ready(
            metadata,
            expected_channel="test",
            runner=refusing_runner,
        )
    assert refusing_runner.calls == []


@pytest.mark.parametrize("residual", ["bundle", "attachment"])
def test_unbound_replay_refuses_residual_image_state(
    tmp_path: Path,
    residual: str,
) -> None:
    """Crash before durable identity binding preserves evidence for recovery."""
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    if residual == "bundle":
        metadata.bundle_path.mkdir()
    runner = FakeRunner(metadata, attached=residual == "attachment")

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert not any(argv[:2] == (volume.HDIUTIL, "create") for argv, _ in runner.calls)
    assert not any(argv[:2] == (volume.HDIUTIL, "detach") for argv, _ in runner.calls)
    assert volume.load_archive_metadata(metadata_path).state == volume.PLANNED_UNBOUND


def test_first_identity_persist_failure_preserves_created_image(tmp_path: Path) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    runner = FakeRunner(metadata, attached=False)

    def fail_writer(_path: Path, _metadata: volume.ArchiveVolumeMetadata) -> None:
        raise OSError("fixture-private-persistence-detail")

    with pytest.raises(volume.ArchiveVolumeRefusedError) as error:
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
            metadata_writer=fail_writer,
        )

    assert "fixture-private-persistence-detail" not in str(error.value)
    assert metadata.bundle_path.exists()
    assert runner.attached is False
    assert not any(argv[:2] == (volume.HDIUTIL, "detach") for argv, _ in runner.calls)
    assert volume.load_archive_metadata(metadata_path) == metadata


def test_provisioning_failed_replay_refuses_preexisting_attachment(
    tmp_path: Path,
) -> None:
    planned = _planned_metadata(tmp_path)
    _materialize_ready_fs(planned)
    residual = replace(planned, generation=1, state=volume.PROVISIONING_FAILED)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, residual)
    runner = FakeRunner(residual, attached=True)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            residual,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert not any(argv[:2] == (volume.HDIUTIL, "attach") for argv, _ in runner.calls)
    assert not any(argv[:2] == (volume.HDIUTIL, "detach") for argv, _ in runner.calls)
    assert volume.load_archive_metadata(metadata_path) == residual


def test_provisioning_failed_replay_requires_fresh_attach(tmp_path: Path) -> None:
    planned = _planned_metadata(tmp_path)
    _materialize_ready_fs(planned)
    residual = replace(planned, generation=1, state=volume.PROVISIONING_FAILED)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, residual)
    runner = FakeRunner(residual, attached=False)

    result = volume.provision_archive_volume(
        residual,
        credential=_PASSPHRASE,
        runner=runner,
        metadata_path=metadata_path,
    )

    assert result.ready is True
    assert sum(argv[:2] == (volume.HDIUTIL, "attach") for argv, _ in runner.calls) == 1
    active = volume.load_archive_metadata(metadata_path)
    assert active.state == volume.BOUND_ACTIVE
    assert active.channel == "prod"
    assert active.filesystem_capacity_bytes == _FILESYSTEM_CAPACITY
    assert active.generation == 3


def test_provisioning_rechecks_image_fingerprint_after_attach(tmp_path: Path) -> None:
    planned = _planned_metadata(tmp_path)
    _materialize_ready_fs(planned)
    residual = replace(planned, generation=1, state=volume.PROVISIONING_FAILED)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, residual)

    class FingerprintSwapRunner(FakeRunner):
        def __call__(
            self,
            argv: tuple[str, ...],
            stdin: bytes | None = None,
            cwd_fd: int | None = None,
        ) -> volume.CommandResult:
            result = super().__call__(argv, stdin, cwd_fd)
            if argv[:2] == (volume.HDIUTIL, "attach"):
                (residual.bundle_path / "Info.plist").write_bytes(
                    _plist({"fixture-image-id": "post-attach-replacement"})
                )
            return result

    runner = FingerprintSwapRunner(residual, attached=False)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            residual,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert (volume.HDIUTIL, "detach", _DEVICE) in [argv for argv, _ in runner.calls]
    assert volume.load_archive_metadata(metadata_path) == residual


def test_attached_identity_replay_promotes_without_regeneration(tmp_path: Path) -> None:
    metadata = _planned_metadata(tmp_path)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    runner = FakeRunner(metadata, attached=False)
    writes: list[str] = []

    def interrupt_before_active(
        path: Path,
        next_metadata: volume.ArchiveVolumeMetadata,
    ) -> None:
        writes.append(next_metadata.state)
        if next_metadata.state == volume.BOUND_ACTIVE:
            raise OSError("fixture-private-after-bind-detail")
        volume.write_archive_metadata(path, next_metadata)

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
            metadata_writer=interrupt_before_active,
        )

    attached = volume.load_archive_metadata(metadata_path)
    assert writes == [
        volume.PROVISIONING_FAILED,
        volume.ATTACHED_VERIFIED,
        volume.BOUND_ACTIVE,
    ]
    assert attached.state == volume.ATTACHED_VERIFIED
    assert attached.channel == "prod"
    assert attached.volume_uuid == _UUID
    assert metadata.bundle_path.exists()

    result = volume.provision_archive_volume(
        attached,
        credential=_PASSPHRASE,
        runner=runner,
        metadata_path=metadata_path,
    )
    assert result.ready is True
    assert volume.load_archive_metadata(metadata_path).state == volume.BOUND_ACTIVE
    assert sum(argv[:2] == (volume.HDIUTIL, "create") for argv, _ in runner.calls) == 1


def test_attached_replay_refuses_uuid_drift_without_regeneration(tmp_path: Path) -> None:
    metadata = replace(
        _metadata(tmp_path),
        generation=2,
        state=volume.ATTACHED_VERIFIED,
    )
    metadata_path = tmp_path / "archive-metadata.json"
    _materialize_ready_fs(metadata)
    volume.write_archive_metadata(metadata_path, metadata)
    runner = FakeRunner(metadata, disk_overrides={"VolumeUUID": "different"})

    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert volume.load_archive_metadata(metadata_path) == metadata
    assert not any(argv[:2] == (volume.HDIUTIL, "create") for argv, _ in runner.calls)


def test_production_startup_and_deploy_validate_without_provisioning() -> None:
    prod = Path("scripts/prod/start_midgard_stack.sh").read_text(encoding="utf-8")
    deploy = Path("scripts/deploy_channel.sh").read_text(encoding="utf-8")
    full_start = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    cold_boot = Path("scripts/cold_boot.sh").read_text(encoding="utf-8")
    companion = Path("scripts/lib/companion_ui_startup.sh").read_text(
        encoding="utf-8"
    )
    makefile = Path("Makefile").read_text(encoding="utf-8")
    helper = Path("scripts/lib/heimdal_cold_volume_preflight.sh").read_text(encoding="utf-8")

    assert "heimdal_cold_volume_preflight prod" in prod
    assert "heimdal_cold_volume_preflight" in deploy
    assert "app.ops.heimdal_cold_volume" in helper
    assert " require-ready" in helper
    assert " provision" not in helper
    assert prod.index("heimdal_cold_volume_preflight prod") < prod.index(
        "exec scripts/start_full_system.sh"
    )
    assert deploy.index("heimdal_cold_volume_preflight") < deploy.index("write_pin")
    assert 'source "scripts/lib/heimdal_cold_volume_preflight.sh"' in full_start
    assert 'heimdal_cold_volume_preflight_effective "$ROOT"' in full_start
    assert full_start.index(
        'heimdal_cold_volume_preflight_effective "$ROOT"'
    ) < full_start.index("prepare_instance_ownership_host_state_dir")
    assert full_start.index(
        'heimdal_cold_volume_preflight_effective "$ROOT"'
    ) < full_start.index('mkdir -p "$ROOT/tmp"')
    assert 'heimdal_cold_volume_preflight.sh"' in companion
    assert "heimdal_cold_volume_preflight_effective" in companion
    companion_start = companion.split("cui_start_runtime() {", maxsplit=1)[1].split(
        "\ncui_compose() {", maxsplit=1
    )[0]
    assert companion_start.index(
        "heimdal_cold_volume_preflight_effective"
    ) < companion_start.index("cui_api_healthy_now")
    prod_up = makefile.split("\nprod-up:", maxsplit=1)[1].split(
        "\nprod-down:", maxsplit=1
    )[0]
    assert "heimdal_cold_volume_preflight prod" in prod_up
    assert prod_up.index("heimdal_cold_volume_preflight prod") < prod_up.index(
        "prepare-instance-ownership"
    )
    assert prod_up.index("heimdal_cold_volume_preflight prod") < prod_up.index(
        "$(COMPOSE_PROD) up"
    )
    assert 'source "scripts/lib/heimdal_cold_volume_preflight.sh"' in cold_boot
    assert 'heimdal_cold_volume_preflight_effective "$ROOT"' in cold_boot
    assert cold_boot.index(
        'heimdal_cold_volume_preflight_effective "$ROOT"'
    ) < cold_boot.index("prepare_instance_ownership_host_state_dir")
    assert cold_boot.index(
        'heimdal_cold_volume_preflight_effective "$ROOT"'
    ) < cold_boot.index("docker compose down -v")
