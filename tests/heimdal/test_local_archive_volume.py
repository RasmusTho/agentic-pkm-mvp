"""HAR-03: encrypted local archive volume boundary (#3849).

Every host command is simulated.  These tests must never attach, create, erase,
partition, or unlock a real disk image or Keychain item.
"""

from __future__ import annotations

import inspect
import json
import os
from dataclasses import replace
from pathlib import Path
import plistlib

import pytest

from app.ops import heimdal_cold_volume as volume
from app.ops.host_secret_contract import load_host_secret_contract


pytestmark = pytest.mark.not_pg

_CAPACITY = 8 * 1024**3
_DEVICE = "/dev/disk9s1"
_UUID = "11111111-2222-3333-4444-555555555555"
_PASSPHRASE = "fixture-secret-never-log"


def _metadata(tmp_path: Path) -> volume.ArchiveVolumeMetadata:
    parent = tmp_path / "external-parent"
    parent.mkdir()
    mountpoint = tmp_path / "archive-mount"
    mountpoint.mkdir()
    mountpoint.chmod(0o700)
    return volume.ArchiveVolumeMetadata(
        state=volume.BOUND_ACTIVE,
        archive_id="heimdal-cold-v1",
        bundle_path=parent / "archive.sparsebundle",
        mountpoint=mountpoint,
        volume_uuid=_UUID,
        capacity_bytes=_CAPACITY,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
        mode=0o700,
    )


def _planned_metadata(tmp_path: Path) -> volume.ArchiveVolumeMetadata:
    return replace(
        _metadata(tmp_path),
        state=volume.PLANNED_UNBOUND,
        volume_uuid=None,
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
        "TotalSize": metadata.capacity_bytes,
        "Internal": False,
        "Encryption": True,
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
            str(self.metadata.bundle_path),
            "-plist",
        ):
            return volume.CommandResult(0, _plist({"encrypted": self.encrypted}))
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
            if self.attach_rc == 0:
                self.attached = True
                self.metadata.mountpoint.chmod(self.metadata.mode)
                return volume.CommandResult(0, _attach_info(self.metadata))
            return volume.CommandResult(self.attach_rc, b"", b"fixture-private-detail")
        if argv[:2] == (volume.HDIUTIL, "create"):
            if cwd_fd is None:
                raise AssertionError("create must carry descriptor-bound authority")
            details = os.fstat(cwd_fd)
            os.mkdir(self.metadata.bundle_path.name, dir_fd=cwd_fd)
            return volume.CommandResult(
                0,
                _plist({}),
                cwd_identity=(details.st_dev, details.st_ino),
            )
        if argv == (volume.HDIUTIL, "detach", _DEVICE):
            self.attached = False
            return volume.CommandResult(0, b"")
        raise AssertionError(f"unexpected command shape: {argv!r}")


def _materialize_ready_fs(metadata: volume.ArchiveVolumeMetadata) -> None:
    metadata.bundle_path.mkdir(exist_ok=True)
    metadata.mountpoint.chmod(metadata.mode)


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
        env={"HOST_SECRET_RUNTIME_ENV_FILE": str(secret_file)},
        runner=runner,
        metadata_path=metadata_path,
    )
    assert result.ready is True
    assert _PASSPHRASE not in repr(result)
    assert all(_PASSPHRASE not in " ".join(argv) for argv, _stdin in runner.calls)


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
            del cwd_fd
            self.calls.append((argv, stdin))
            if argv == (volume.HDIUTIL, "info", "-plist"):
                self.info_calls += 1
                if self.info_calls == 1:
                    return volume.CommandResult(0, _plist({"images": []}))
                return volume.CommandResult(0, _plist({}))
            if argv[:2] == (volume.HDIUTIL, "attach"):
                self.attached = True
                return volume.CommandResult(0, _attach_info(metadata))
            if argv == (volume.HDIUTIL, "detach", _DEVICE):
                if detach_rc == 0:
                    self.attached = False
                return volume.CommandResult(detach_rc, b"", b"fixture-private-detail")
            raise AssertionError(f"unexpected command shape: {argv!r}")

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
            self.calls.append((argv, stdin))
            original_parent.rename(displaced_parent)
            original_parent.mkdir()
            if cwd_fd is None:
                metadata.bundle_path.mkdir()
                return volume.CommandResult(0, _plist({}))
            held = os.fstat(cwd_fd)
            self.create_cwd_identity = (held.st_dev, held.st_ino)
            os.mkdir(metadata.bundle_path.name, dir_fd=cwd_fd)
            return volume.CommandResult(
                0,
                _plist({}),
                cwd_identity=self.create_cwd_identity,
            )

    runner = ParentSwapRunner(metadata, attached=False)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.provision_archive_volume(
            metadata,
            credential=_PASSPHRASE,
            runner=runner,
            metadata_path=metadata_path,
        )

    assert runner.create_cwd_identity is not None
    assert not (displaced_parent / metadata.bundle_path.name).exists()
    assert not metadata.bundle_path.exists()
    assert volume.load_archive_metadata(metadata_path) == metadata


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
        pytest.param({"Encryption": False}, id="disk-encryption-false"),
        pytest.param({"Encryption": "true"}, id="wrong-encryption-type"),
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


def test_command_adapter_is_allowlisted_bounded_and_redacted(tmp_path: Path) -> None:
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

    parent_descriptor = os.open(metadata.bundle_path.parent, os.O_RDONLY)
    try:
        result = volume.run_command(
            volume.create_command(metadata),
            metadata,
            _PASSPHRASE.encode(),
            parent_descriptor,
            executor=descriptor_executor,
        )
        details = os.fstat(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    assert captured["cwd"] == f"/dev/fd/{parent_descriptor}"
    assert captured["pass_fds"] == (parent_descriptor,)
    assert captured["argv"][-1] == metadata.bundle_path.name
    assert result.cwd_identity == (details.st_dev, details.st_ino)


def test_metadata_is_closed_value_free_and_atomic(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(path, metadata)
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".archive-metadata.json.*")) == []
    assert volume.load_archive_metadata(path) == metadata

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["credential"] = _PASSPHRASE
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        volume.load_archive_metadata(path)


@pytest.mark.parametrize(
    ("state", "volume_uuid"),
    [
        pytest.param(volume.PLANNED_UNBOUND, _UUID, id="planned-with-identity"),
        pytest.param(volume.ATTACHED_VERIFIED, None, id="attached-without-identity"),
        pytest.param(volume.BOUND_ACTIVE, None, id="active-without-identity"),
    ],
)
def test_metadata_state_and_identity_are_coherent(
    tmp_path: Path,
    state: str,
    volume_uuid: str | None,
) -> None:
    metadata = _metadata(tmp_path)
    with pytest.raises(volume.ArchiveVolumeRefusedError):
        replace(metadata, state=state, volume_uuid=volume_uuid)


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


def test_first_identity_persist_failure_cleans_only_created_image(tmp_path: Path) -> None:
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
    assert not metadata.bundle_path.exists()
    assert runner.attached is False
    assert (volume.HDIUTIL, "detach", _DEVICE) in [argv for argv, _ in runner.calls]
    assert volume.load_archive_metadata(metadata_path) == metadata


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
    assert writes == [volume.ATTACHED_VERIFIED, volume.BOUND_ACTIVE]
    assert attached.state == volume.ATTACHED_VERIFIED
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
    metadata = replace(_metadata(tmp_path), state=volume.ATTACHED_VERIFIED)
    metadata_path = tmp_path / "archive-metadata.json"
    volume.write_archive_metadata(metadata_path, metadata)
    _materialize_ready_fs(metadata)
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
