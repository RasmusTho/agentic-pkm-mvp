from __future__ import annotations

import hashlib
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

import pytest

import app.knowledge.atomic_append_reconcile as atomic_append_module
from app.knowledge.atomic_append_reconcile import (
    AtomicAppendIdentityCollision,
    AtomicAppendRecoveryError,
    atomic_append_reconcile_relative,
)
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.write_guard import WriteGuard
from tests.knowledge.linux_acl import (
    LinuxNamedAclUnavailable,
    create_linux_named_acl_file,
    read_linux_access_acl,
)


def _healthy_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _fingerprint(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unchanged(payload: bytes, _records: object) -> bytes:
    return payload


def _active_stage_paths(parent: Path) -> list[Path]:
    return sorted(parent.glob(".atomic-append-reconcile-*.stage-*"))


def _retained_stage_paths(parent: Path) -> list[Path]:
    retention = parent / ".atomic-append-reconcile-recovery"
    return sorted(retention.glob("*.recovery")) if retention.exists() else []


def _replace_cleanup_candidate(
    parent_fd: int,
    stage_name: str,
    *,
    payload: bytes,
) -> None:
    os.unlink(stage_name, dir_fd=parent_fd)
    replacement_fd = os.open(
        stage_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=parent_fd,
    )
    try:
        os.write(replacement_fd, payload)
        os.fsync(replacement_fd)
    finally:
        os.close(replacement_fd)
    os.fsync(parent_fd)


def _concurrent_append(vault: str, operation_id: str, queue: object) -> None:
    result = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id=operation_id,
        payload=f"entry:{operation_id}",
        payload_fingerprint=_fingerprint(f"entry:{operation_id}"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    queue.put(result.outcome)  # type: ignore[union-attr]


def test_identity_cas_replays_identical_payload_and_rejects_collision(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    first = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="stable-op-1",
        payload="first payload",
        payload_fingerprint=_fingerprint("first payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    replay = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="stable-op-1",
        payload="first payload",
        payload_fingerprint=_fingerprint("first payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )

    assert first.outcome == "appended"
    assert replay.outcome == "reconciled_replay"
    assert (vault / "Logs" / "steering.md").read_text().count("stable-op-1") == 2

    with pytest.raises(AtomicAppendIdentityCollision):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="stable-op-1",
            payload="different payload",
            payload_fingerprint=_fingerprint("different payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )


def test_concurrent_writers_linearize_by_anchored_identity_cas(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    operations = [f"concurrent-{index}" for index in range(4)]
    processes = [
        context.Process(target=_concurrent_append, args=(str(vault), operation_id, queue))
        for operation_id in operations
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sorted(queue.get(timeout=2) for _ in operations) == ["appended"] * len(operations)
    content = (vault / "Logs" / "steering.md").read_text()
    assert all(content.count(operation_id) == 2 for operation_id in operations)


def test_framed_record_recovery_rejects_partial_commit_and_reconciles_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir()
    target.write_bytes(atomic_append_module._FRAME_PREFIX + b'{"id":"torn')

    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="recoverable-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    target.write_text("")
    stage_name = atomic_append_module._stage_prefix(
        "steering.md", "orphan-op", _fingerprint("payload")
    ) + "crashed"
    (target.parent / stage_name).write_bytes(atomic_append_module._FRAME_PREFIX[:8])
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="orphan-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    (target.parent / stage_name).unlink()

    target.write_text("")
    real_exchange = atomic_append_module._atomic_exchange_at

    def exchange_then_fail(*args: object) -> None:
        real_exchange(*args)  # type: ignore[arg-type]
        raise OSError("injected post-publication uncertainty")

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", exchange_then_fail)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="recoverable-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="recoverable-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    replay = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="recoverable-op",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert replay.outcome == "reconciled_replay"
    assert target.read_text().count("recoverable-op") == 2

    target.write_bytes(atomic_append_module._FRAME_PREFIX[:8])
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="short-prefix-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )


def test_anchored_vault_path_and_directory_fsync_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def traced_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    atomic_append_reconcile_relative(
        "new-parent/deeper/record.md",
        operation_id="anchored-op",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert fsync_calls

    (vault / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises((KnowledgeCapabilityError, OSError)):
        atomic_append_reconcile_relative(
            "alias/escaped.md",
            operation_id="escaped-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    linked_target = vault / "linked.md"
    linked_target.write_text("linked")
    os.link(linked_target, vault / "linked-alias.md")
    with pytest.raises(KnowledgeCapabilityError):
        atomic_append_reconcile_relative(
            "linked.md",
            operation_id="hard-link-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert not list(vault.glob(".atomic-append-reconcile-*.lock"))
    assert not (outside / "escaped.md").exists()

    target_alias = vault / "target-alias.md"
    target_alias.symlink_to(outside / "target.md")
    with pytest.raises((KnowledgeCapabilityError, OSError)):
        atomic_append_reconcile_relative(
            "target-alias.md",
            operation_id="target-alias-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    renamed_target = vault / "renamed.md"
    renamed_target.write_text("before-rename")
    parent_fd = os.open(renamed_target.parent, os.O_RDONLY)
    target_fd = os.open(renamed_target, os.O_RDONLY)
    try:
        target_stat = os.fstat(target_fd)
        os.rename(renamed_target, vault / ".atomic-append-reconcile-forged.stage-")
        with pytest.raises(KnowledgeWriteConflict):
            atomic_append_module._canonical_target_entry(parent_fd, "renamed.md", target_stat)
    finally:
        os.close(target_fd)
        os.close(parent_fd)


def test_replacement_preserves_metadata_or_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    linux_access_acl: str | None = None
    if sys.platform == "linux":
        try:
            linux_fixture = create_linux_named_acl_file(target, content=b"existing")
        except LinuxNamedAclUnavailable as exc:
            pytest.fail(str(exc))
        linux_access_acl = linux_fixture.access_acl
    elif sys.platform == "darwin":
        target.write_text("existing")
        target.chmod(0o640)
        acl_change = subprocess.run(
            ["chmod", "+a", "everyone allow read", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if acl_change.returncode != 0:
            pytest.fail(f"cannot create a non-trivial filesystem ACL: {acl_change.stderr}")
    else:
        pytest.fail("AC5 requires Linux POSIX ACLs or macOS descriptor ACLs")

    target_fd = os.open(target, os.O_RDONLY)
    try:
        atomic_append_module._set_xattr(target_fd, "user.atomic_append_test", b"preserve")
        acl_before = atomic_append_module._acl_text(target_fd)
        if linux_access_acl is not None:
            assert sum(line.startswith(b"user:") for line in acl_before.splitlines()) >= 2
        else:
            assert b"everyone" in acl_before
    finally:
        os.close(target_fd)

    atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="metadata-op",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    target_fd = os.open(target, os.O_RDONLY)
    try:
        assert atomic_append_module._get_xattr(target_fd, "user.atomic_append_test") == b"preserve"
        assert atomic_append_module._acl_text(target_fd) == acl_before
    finally:
        os.close(target_fd)
    if linux_access_acl is not None:
        assert read_linux_access_acl(target) == linux_access_acl
    assert target.stat().st_uid == os.getuid()
    assert target.stat().st_gid == os.getgid()

    original = target.read_bytes()
    real_set_xattr = atomic_append_module._set_xattr

    def reject_xattr(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected xattr failure")

    monkeypatch.setattr(atomic_append_module, "_set_xattr", reject_xattr)
    with pytest.raises(KnowledgeCapabilityError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="metadata-failure-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_bytes() == original

    monkeypatch.setattr(atomic_append_module, "_set_xattr", real_set_xattr)

    def reject_acl(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected ACL clone failure")

    monkeypatch.setattr(atomic_append_module, "_clone_acl", reject_acl)
    with pytest.raises(KnowledgeCapabilityError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="acl-failure-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_bytes() == original


def test_failure_points_are_fail_loud_and_retry_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    kwargs = {
        "payload": "payload",
        "payload_fingerprint": _fingerprint("payload"),
        "vault_root": vault,
        "action": "test.atomic_append",
        "write_guard": _healthy_guard(),
        "reconcile": _unchanged,
    }

    def reject_reconcile(_candidate: bytes, _records: object) -> bytes:
        raise OSError("injected reconciliation failure")

    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            **{
                **kwargs,
                "operation_id": "reconcile-fault-op",
                "reconcile": reject_reconcile,
            },
        )
    assert target.read_text() == "original"

    real_exchange = atomic_append_module._atomic_exchange_at

    def reject_exchange(*_args: object) -> None:
        raise OSError("injected pre-effect exchange failure")

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", reject_exchange)
    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "exchange-fault-op"}
        )
    assert target.read_text() == "original"
    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", real_exchange)

    real_write_all = atomic_append_module._write_all
    real_fsync = os.fsync

    def partial_write_then_fail(fd: int, payload: bytes) -> None:
        real_write_all(fd, payload[: max(1, len(payload) // 2)])
        raise OSError("injected partial record write failure")

    monkeypatch.setattr(atomic_append_module, "_write_all", partial_write_then_fail)
    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "partial-write-fault-op"}
        )
    assert target.read_text() == "original"
    monkeypatch.setattr(atomic_append_module, "_write_all", real_write_all)

    stage_write_finished = False

    def write_then_arm(fd: int, payload: bytes) -> None:
        nonlocal stage_write_finished
        real_write_all(fd, payload)
        stage_write_finished = True

    def reject_record_fsync(fd: int) -> None:
        if stage_write_finished:
            raise OSError("injected record fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(atomic_append_module, "_write_all", write_then_arm)
    monkeypatch.setattr(os, "fsync", reject_record_fsync)
    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "record-fsync-fault-op"}
        )
    assert target.read_text() == "original"
    monkeypatch.setattr(atomic_append_module, "_write_all", real_write_all)
    monkeypatch.setattr(os, "fsync", real_fsync)

    real_rename_noreplace = atomic_append_module._atomic_rename_noreplace_at

    def reject_retirement(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        if source_name.startswith(".atomic-append-reconcile-"):
            raise OSError("injected cleanup retirement failure")
        real_rename_noreplace(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(
        atomic_append_module,
        "_atomic_rename_noreplace_at",
        reject_retirement,
    )
    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "retirement-fault-op"}
        )
    monkeypatch.setattr(
        atomic_append_module,
        "_atomic_rename_noreplace_at",
        real_rename_noreplace,
    )
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "retirement-fault-op"}
        )
    replay = atomic_append_reconcile_relative(
        "Logs/steering.md", **{**kwargs, "operation_id": "retirement-fault-op"}
    )
    assert replay.outcome == "reconciled_replay"

    cleanup_fsync = False

    def retire_then_arm(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal cleanup_fsync
        real_rename_noreplace(
            source_fd,
            source_name,
            destination_fd,
            destination_name,
        )
        if source_name.startswith(".atomic-append-reconcile-"):
            cleanup_fsync = True

    def reject_cleanup_fsync(fd: int) -> None:
        if cleanup_fsync:
            raise OSError("injected cleanup directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(
        atomic_append_module,
        "_atomic_rename_noreplace_at",
        retire_then_arm,
    )
    monkeypatch.setattr(os, "fsync", reject_cleanup_fsync)
    with pytest.raises(OSError):
        atomic_append_reconcile_relative(
            "Logs/steering.md", **{**kwargs, "operation_id": "cleanup-fsync-op"}
        )
    monkeypatch.setattr(
        atomic_append_module,
        "_atomic_rename_noreplace_at",
        real_rename_noreplace,
    )
    monkeypatch.setattr(os, "fsync", real_fsync)
    retry = atomic_append_reconcile_relative(
        "Logs/steering.md", **{**kwargs, "operation_id": "cleanup-fsync-op"}
    )
    assert retry.outcome == "reconciled_replay"


def test_cleanup_race_retains_foreign_prepublication_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    foreign = b"foreign-prepublication-entry"
    real_retire = atomic_append_module._retire_owned_stage
    real_exchange = atomic_append_module._atomic_exchange_at
    retirement_injected = False

    def reject_exchange(*args: object) -> None:
        del args
        raise OSError("injected failure before publication")

    def replace_immediately_before_retirement(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        retention_fd: int,
        capacity: object,
    ) -> object:
        nonlocal retirement_injected
        assert stat.S_ISREG(os.fstat(owner_fd).st_mode)
        if not retirement_injected:
            retirement_injected = True
            _replace_cleanup_candidate(parent_fd, stage_name, payload=foreign)
        return real_retire(parent_fd, stage_name, owner_fd, retention_fd, capacity)

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", reject_exchange)
    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        replace_immediately_before_retirement,
    )

    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="prepublication-cleanup-race",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", real_exchange)

    assert retirement_injected
    assert target.read_text() == "original"
    retained_or_active = _retained_stage_paths(target.parent) + _active_stage_paths(target.parent)
    assert foreign in {path.read_bytes() for path in retained_or_active}


def test_cleanup_race_retains_foreign_displaced_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    foreign = b"foreign-displaced-entry"
    real_retire = atomic_append_module._retire_owned_stage
    retirement_injected = False

    def replace_immediately_before_retirement(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        retention_fd: int,
        capacity: object,
    ) -> object:
        nonlocal retirement_injected
        assert os.pread(owner_fd, len(b"original"), 0) == b"original"
        if not retirement_injected:
            retirement_injected = True
            _replace_cleanup_candidate(parent_fd, stage_name, payload=foreign)
        return real_retire(parent_fd, stage_name, owner_fd, retention_fd, capacity)

    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        replace_immediately_before_retirement,
    )

    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="displaced-cleanup-race",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    assert retirement_injected
    assert "displaced-cleanup-race" in target.read_text()
    retained_or_active = _retained_stage_paths(target.parent) + _active_stage_paths(target.parent)
    assert foreign in {path.read_bytes() for path in retained_or_active}

    monkeypatch.setattr(atomic_append_module, "_retire_owned_stage", real_retire)
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="displaced-cleanup-race",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    replay = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="displaced-cleanup-race",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert replay.outcome == "reconciled_replay"
    assert target.read_text().count("displaced-cleanup-race") == 2


def test_owned_cleanup_preserves_atomic_append_replay_semantics(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    kwargs = {
        "operation_id": "owned-cleanup",
        "payload": "payload",
        "payload_fingerprint": _fingerprint("payload"),
        "vault_root": vault,
        "action": "test.atomic_append",
        "write_guard": _healthy_guard(),
        "reconcile": _unchanged,
    }

    first = atomic_append_reconcile_relative("Logs/steering.md", **kwargs)
    replay = atomic_append_reconcile_relative("Logs/steering.md", **kwargs)

    assert first.outcome == "appended"
    assert replay.outcome == "reconciled_replay"
    assert target.read_text().count("owned-cleanup") == 2
    assert _active_stage_paths(target.parent) == []
    retained = _retained_stage_paths(target.parent)
    assert retained
    assert all(path.suffix == ".recovery" for path in retained)


def test_cleanup_restore_collision_retains_every_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    foreign = b"foreign-before-restore"
    later = b"later-active-entrant"
    real_retire = atomic_append_module._retire_owned_stage
    real_rename = atomic_append_module._atomic_rename_noreplace_at
    retiring_name = ""
    moved_to_recovery = False

    def collide_during_restore(
        source_fd: int,
        source_name: str,
        destination_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal moved_to_recovery
        if destination_name == retiring_name and moved_to_recovery:
            entrant_fd = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=destination_fd,
            )
            try:
                os.write(entrant_fd, later)
                os.fsync(entrant_fd)
            finally:
                os.close(entrant_fd)
            os.fsync(destination_fd)
        real_rename(source_fd, source_name, destination_fd, destination_name)
        if source_name == retiring_name:
            moved_to_recovery = True

    def replace_before_retirement(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        recovery_fd: int,
        capacity: object,
    ) -> object:
        nonlocal retiring_name
        retiring_name = stage_name
        _replace_cleanup_candidate(parent_fd, stage_name, payload=foreign)
        return real_retire(parent_fd, stage_name, owner_fd, recovery_fd, capacity)

    monkeypatch.setattr(
        atomic_append_module,
        "_atomic_rename_noreplace_at",
        collide_during_restore,
    )
    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        replace_before_retirement,
    )
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="restore-collision",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    assert later in {path.read_bytes() for path in _active_stage_paths(target.parent)}
    retained_bytes = {path.read_bytes() for path in _retained_stage_paths(target.parent)}
    assert foreign in retained_bytes
    assert b"original" in retained_bytes


def test_retained_name_substitution_fails_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    replacement = b"foreign-retained-substitution"
    real_retire = atomic_append_module._retire_owned_stage

    def substitute_retained_name(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        recovery_fd: int,
        capacity: object,
    ) -> object:
        receipt = real_retire(parent_fd, stage_name, owner_fd, recovery_fd, capacity)
        os.unlink(receipt.name, dir_fd=recovery_fd)
        replacement_fd = os.open(
            receipt.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=recovery_fd,
        )
        try:
            os.write(replacement_fd, replacement)
            os.fsync(replacement_fd)
        finally:
            os.close(replacement_fd)
        os.fsync(recovery_fd)
        return receipt

    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        substitute_retained_name,
    )
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="retained-substitution",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    retained_bytes = {path.read_bytes() for path in _retained_stage_paths(target.parent)}
    assert replacement in retained_bytes
    assert b"original" in retained_bytes


def test_mid_retirement_substitution_snapshots_unlinked_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    replacement = b"foreign-mid-retirement"
    real_retire = atomic_append_module._retire_owned_stage
    real_fstat = os.fstat

    def substitute_between_retained_and_owner_stat(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        recovery_fd: int,
        capacity: object,
    ) -> object:
        owner_stat_calls = 0

        def injecting_fstat(fd: int) -> os.stat_result:
            nonlocal owner_stat_calls
            if fd == owner_fd:
                owner_stat_calls += 1
                if owner_stat_calls == 2:
                    retained_name = next(
                        name
                        for name in os.listdir(recovery_fd)
                        if name.startswith(stage_name) and name.endswith(".recovery")
                    )
                    os.unlink(retained_name, dir_fd=recovery_fd)
                    replacement_fd = os.open(
                        retained_name,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=recovery_fd,
                    )
                    try:
                        os.write(replacement_fd, replacement)
                        os.fsync(replacement_fd)
                    finally:
                        os.close(replacement_fd)
                    os.fsync(recovery_fd)
            return real_fstat(fd)

        monkeypatch.setattr(os, "fstat", injecting_fstat)
        try:
            return real_retire(
                parent_fd,
                stage_name,
                owner_fd,
                recovery_fd,
                capacity,
            )
        finally:
            monkeypatch.setattr(os, "fstat", real_fstat)

    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        substitute_between_retained_and_owner_stat,
    )
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="mid-retirement-substitution",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    retained_bytes = {path.read_bytes() for path in _retained_stage_paths(target.parent)}
    assert replacement in retained_bytes
    assert b"original" in retained_bytes


def test_late_active_stage_entry_prevents_success_and_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    late = b"late-active-stage"
    real_retire = atomic_append_module._retire_owned_stage

    def add_late_active_entry(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        recovery_fd: int,
        capacity: object,
    ) -> object:
        receipt = real_retire(parent_fd, stage_name, owner_fd, recovery_fd, capacity)
        late_fd = os.open(
            f"{stage_name}late",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        try:
            os.write(late_fd, late)
            os.fsync(late_fd)
        finally:
            os.close(late_fd)
        os.fsync(parent_fd)
        return receipt

    monkeypatch.setattr(
        atomic_append_module,
        "_retire_owned_stage",
        add_late_active_entry,
    )
    kwargs = {
        "operation_id": "late-active",
        "payload": "payload",
        "payload_fingerprint": _fingerprint("payload"),
        "vault_root": vault,
        "action": "test.atomic_append",
        "write_guard": _healthy_guard(),
        "reconcile": _unchanged,
    }
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative("Logs/steering.md", **kwargs)
    assert late in {path.read_bytes() for path in _active_stage_paths(target.parent)}

    monkeypatch.setattr(atomic_append_module, "_retire_owned_stage", real_retire)
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative("Logs/steering.md", **kwargs)
    replay = atomic_append_reconcile_relative("Logs/steering.md", **kwargs)
    assert replay.outcome == "reconciled_replay"


def test_malformed_retained_inventory_fails_before_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    recovery = target.parent / atomic_append_module._RECOVERY_DIRECTORY
    recovery.mkdir()
    scope = atomic_append_module._stage_scope_prefix("steering.md", "malformed-retained")
    (recovery / f"{scope}malformed.retained.recovery").write_bytes(
        atomic_append_module._FRAME_PREFIX[:8]
    )

    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="malformed-retained",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_text() == "original"
    assert _active_stage_paths(target.parent) == []


def test_recovery_capacity_refuses_before_stage_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    recovery = target.parent / atomic_append_module._RECOVERY_DIRECTORY
    recovery.mkdir()
    (recovery / "preexisting.recovery").write_text("evidence")
    monkeypatch.setattr(atomic_append_module, "_MAX_RECOVERY_ENTRIES", 2)

    with pytest.raises(KnowledgeCapabilityError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="capacity-refusal",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_text() == "original"
    assert _active_stage_paths(target.parent) == []


def test_reservation_descriptor_open_failure_restores_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    monkeypatch.setattr(atomic_append_module, "_MAX_RECOVERY_ENTRIES", 2)
    real_open = os.open
    fail_reserved_open = True

    def open_with_reservation_failure(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal fail_reserved_open
        if fail_reserved_open and os.fsdecode(path).startswith("reserved-"):
            fail_reserved_open = False
            raise OSError("injected reservation descriptor open failure")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_with_reservation_failure)
    with pytest.raises(OSError, match="injected reservation descriptor open failure"):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="reservation-open-failure",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    capacity = (
        target.parent
        / atomic_append_module._RECOVERY_DIRECTORY
        / atomic_append_module._CAPACITY_DIRECTORY
    )
    assert sorted(path.name for path in capacity.glob("free-*")) == [
        "free-0000",
        "free-0001",
    ]
    assert list(capacity.glob("reserved-*")) == []

    result = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="reservation-open-retry",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert result.outcome == "appended"


def test_concurrent_capacity_reservations_refuse_before_stage_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(atomic_append_module, "_MAX_RECOVERY_ENTRIES", 2)
    real_reserve = atomic_append_module._reserve_recovery_capacity
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def synchronized_reserve(recovery_fd: int) -> object:
        barrier.wait(timeout=5)
        return real_reserve(recovery_fd)

    def append(target_name: str) -> None:
        try:
            result = atomic_append_reconcile_relative(
                f"Logs/{target_name}.md",
                operation_id=f"capacity-{target_name}",
                payload="payload",
                payload_fingerprint=_fingerprint("payload"),
                vault_root=vault,
                action="test.atomic_append",
                write_guard=_healthy_guard(),
                reconcile=_unchanged,
            )
        except KnowledgeCapabilityError:
            outcomes.append("refused")
        else:
            outcomes.append(result.outcome)

    monkeypatch.setattr(
        atomic_append_module,
        "_reserve_recovery_capacity",
        synchronized_reserve,
    )
    threads = [threading.Thread(target=append, args=(str(index),)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["appended", "refused", "refused"]
    recovery = vault / "Logs" / atomic_append_module._RECOVERY_DIRECTORY
    assert len(list(recovery.glob("*.recovery"))) == 1
    assert _active_stage_paths(vault / "Logs") == []


def test_inventory_enumeration_race_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    operation_id = "inventory-race"
    scope = atomic_append_module._stage_scope_prefix("steering.md", operation_id)
    real_inventory_names = atomic_append_module._stage_inventory_names
    calls = 0

    def inject_during_enumeration(
        parent_fd: int,
        recovery_fd: int,
        scope_prefix: str,
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            entrant_fd = os.open(
                f"{scope}late",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
            os.close(entrant_fd)
            os.fsync(parent_fd)
        return real_inventory_names(parent_fd, recovery_fd, scope_prefix)

    monkeypatch.setattr(
        atomic_append_module,
        "_stage_inventory_names",
        inject_during_enumeration,
    )
    with pytest.raises(AtomicAppendRecoveryError):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id=operation_id,
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_text() == "original"


def test_retained_recovery_is_scanner_inert(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    result = atomic_append_reconcile_relative(
        "Logs/steering.md",
        operation_id="scanner-inert",
        payload="payload",
        payload_fingerprint=_fingerprint("payload"),
        vault_root=vault,
        action="test.atomic_append",
        write_guard=_healthy_guard(),
        reconcile=_unchanged,
    )
    assert result.outcome == "appended"
    assert [path.relative_to(vault) for path in vault.rglob("*.md")] == [
        Path("Logs/steering.md")
    ]
    assert _retained_stage_paths(vault / "Logs")


def test_vault_chain_or_metadata_swap_fails_without_a_success_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer = tmp_path / "outer"
    vault = outer / "vault"
    vault.mkdir(parents=True)
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir()
    target.write_text("original")
    real_exchange = atomic_append_module._atomic_exchange_at

    def exchange_then_replace_root(*args: object) -> None:
        real_exchange(*args)  # type: ignore[arg-type]
        os.rename(vault, outer / "detached-vault")
        vault.mkdir()

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", exchange_then_replace_root)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="root-swap-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
    )
    assert not (vault / "Logs" / "steering.md").exists()
    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", real_exchange)

    vault = outer / "metadata-vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    target.chmod(0o640)
    real_snapshot = atomic_append_module._snapshot_metadata
    snapshots = 0

    def changed_metadata(fd: int) -> object:
        nonlocal snapshots
        snapshots += 1
        if snapshots == 2:
            os.fchmod(fd, 0o600)
        return real_snapshot(fd)

    monkeypatch.setattr(atomic_append_module, "_snapshot_metadata", changed_metadata)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="metadata-swap-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
    assert target.read_text() == "original"

    vault = outer / "tamper-vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    real_retire = atomic_append_module._retire_owned_stage

    def retire_then_tamper(
        parent_fd: int,
        stage_name: str,
        owner_fd: int,
        recovery_fd: int,
        capacity: object,
    ) -> object:
        receipt = real_retire(parent_fd, stage_name, owner_fd, recovery_fd, capacity)
        target_fd = os.open("steering.md", os.O_WRONLY, dir_fd=parent_fd)
        try:
            os.write(target_fd, b"tampered")
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
        return receipt

    monkeypatch.setattr(atomic_append_module, "_retire_owned_stage", retire_then_tamper)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="tamper-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )


def test_late_hard_link_at_each_publication_side_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "target-link-vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")
    real_exchange = atomic_append_module._atomic_exchange_at

    def exchange_with_displaced_alias(
        parent_fd: int, target_name: str, stage_parent_fd: int, stage_name: str
    ) -> None:
        os.link(
            target_name,
            "displaced-alias.md",
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        real_exchange(parent_fd, target_name, stage_parent_fd, stage_name)

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", exchange_with_displaced_alias)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="target-link-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )

    vault = tmp_path / "stage-link-vault"
    target = vault / "Logs" / "steering.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")

    def exchange_with_published_alias(
        parent_fd: int, target_name: str, stage_parent_fd: int, stage_name: str
    ) -> None:
        os.link(
            stage_name,
            "published-alias.md",
            src_dir_fd=stage_parent_fd,
            dst_dir_fd=stage_parent_fd,
            follow_symlinks=False,
        )
        real_exchange(parent_fd, target_name, stage_parent_fd, stage_name)

    monkeypatch.setattr(atomic_append_module, "_atomic_exchange_at", exchange_with_published_alias)
    with pytest.raises(KnowledgeWriteConflict):
        atomic_append_reconcile_relative(
            "Logs/steering.md",
            operation_id="stage-link-op",
            payload="payload",
            payload_fingerprint=_fingerprint("payload"),
            vault_root=vault,
            action="test.atomic_append",
            write_guard=_healthy_guard(),
            reconcile=_unchanged,
        )
