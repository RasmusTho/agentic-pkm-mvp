from __future__ import annotations

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import BinaryIO

import pytest

from app.knowledge import adapters as adapters_module
from app.knowledge.adapters import FsVaultAdapter
from app.knowledge.contracts import NoteLocator
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge.multiwriter import (
    NoteClass,
    WriteOperation,
    classify_note,
    conflict_artifact_path,
    is_conflict_artifact,
)
from app.knowledge.write_ops import write_note_from_absolute


class _FaultingBinaryHandle:
    def __init__(self, handle: BinaryIO, fault: str) -> None:
        self._handle = handle
        self._fault = fault

    def __enter__(self) -> _FaultingBinaryHandle:
        self._handle.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._handle.__exit__(exc_type, exc, traceback)

    def write(self, data: bytes) -> int:
        if self._fault == "write":
            raise OSError("simulated staged write failure")
        return self._handle.write(data)

    def flush(self) -> None:
        if self._fault == "flush":
            raise OSError("simulated staged flush failure")
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()


def _open_fd_count() -> int:
    fd_root = Path("/proc/self/fd")
    if not fd_root.exists():
        fd_root = Path("/dev/fd")
    return len(list(fd_root.iterdir()))


def _has_open_file_identity(expected: os.stat_result) -> bool:
    for fd in range(1024):
        try:
            current = os.fstat(fd)
        except OSError:
            continue
        if (
            current.st_dev,
            current.st_ino,
            stat.S_IFMT(current.st_mode),
        ) == (
            expected.st_dev,
            expected.st_ino,
            stat.S_IFMT(expected.st_mode),
        ):
            return True
    return False


def _install_staged_io_fault(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fault: str,
    fdopen_call: int,
    regular_fsync_call: int,
) -> None:
    if fault in {"write", "flush"}:
        real_fdopen = os.fdopen
        calls = 0

        def faulting_fdopen(
            fd: int,
            *args: object,
            **kwargs: object,
        ) -> object:
            nonlocal calls
            calls += 1
            handle = real_fdopen(fd, *args, **kwargs)
            if calls == fdopen_call:
                return _FaultingBinaryHandle(handle, fault)
            return handle

        monkeypatch.setattr(os, "fdopen", faulting_fdopen)
        return

    real_fsync = os.fsync
    regular_fsyncs = 0

    def faulting_fsync(fd: int) -> None:
        nonlocal regular_fsyncs
        if stat.S_ISREG(os.fstat(fd).st_mode):
            regular_fsyncs += 1
            if regular_fsyncs == regular_fsync_call:
                raise OSError("simulated staged fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", faulting_fsync)


@pytest.mark.parametrize(
    ("path", "operation", "expected"),
    [
        ("_heimdal/settings.md", WriteOperation.WRITE, NoteClass.REWRITTEN),
        ("_heimdal/steering.log.md", WriteOperation.APPEND, NoteClass.APPEND_ONLY),
        ("_heimdal/steering.log.md", WriteOperation.WRITE, NoteClass.REWRITTEN),
        ("_heimdal/watchlist.md", WriteOperation.APPEND, NoteClass.APPEND_ONLY),
        ("_heimdal/never.md", WriteOperation.APPEND, NoteClass.APPEND_ONLY),
        ("Notes/human.md", WriteOperation.WRITE, NoteClass.REWRITTEN),
        ("⚙️ System/companions/card.md", WriteOperation.WRITE, NoteClass.REWRITTEN),
        ("📥 Inbox/inbox.md", WriteOperation.APPEND, NoteClass.APPEND_ONLY),
        ("event-log/entries.md", WriteOperation.APPEND, NoteClass.APPEND_ONLY),
        ("Sources/import.md", WriteOperation.WRITE, NoteClass.CREATE_ONCE),
        ("Episodes/today.md", WriteOperation.WRITE, NoteClass.REWRITTEN),
    ],
)
def test_runtime_note_classes_match_published_contract_rows(
    path: str, operation: WriteOperation, expected: NoteClass
) -> None:
    assert classify_note(path, operation, capture_note_rel="📥 Inbox/inbox.md") is expected


def test_runtime_note_classes_accept_settings_resolved_capture_and_sources_paths() -> None:
    assert (
        classify_note(
            "Custom Capture/capture.md",
            WriteOperation.APPEND,
            capture_note_rel="Custom Capture/capture.md",
        )
        is NoteClass.APPEND_ONLY
    )
    assert (
        classify_note(
            "Acquired/item.md",
            WriteOperation.WRITE,
            sources_root_rel="Acquired",
        )
        is NoteClass.CREATE_ONCE
    )


def test_expected_version_write_rejects_create_once_note_before_mutation(
    tmp_path: Path,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Sources/panel-source.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"concurrent human source")
    stale_version = hashlib.sha256(b"observed source").hexdigest()

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write requires a rewritten note class",
    ):
        adapter.write_note(
            locator,
            "stale watcher proposal",
            expected_version=stale_version,
            writer_identity="watcher",
        )

    assert target.read_bytes() == b"concurrent human source"
    assert list(target.parent.iterdir()) == [target]


def test_adapter_classifies_canonical_target_before_expected_version_write(
    tmp_path: Path,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    target = tmp_path / "Sources" / "panel-source.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"canonical source")
    alias = tmp_path / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / target.name)
    locator = NoteLocator(vault="Vault", path="Notes/source-alias.md")
    expected_version = hashlib.sha256(b"canonical source").hexdigest()

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write rejects aliased note locator",
    ):
        adapter.write_note(
            locator,
            "stale watcher proposal",
            expected_version=expected_version,
            writer_identity="watcher",
        )

    assert target.read_bytes() == b"canonical source"
    assert alias.read_bytes() == b"canonical source"


def test_expected_version_parent_walk_rejects_ancestor_symlink_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    original = tmp_path / "Notes" / "Sub" / "a.md"
    redirected = tmp_path / "Other" / "Sub" / "a.md"
    original.parent.mkdir(parents=True)
    redirected.parent.mkdir(parents=True)
    original.write_bytes(b"same content")
    redirected.write_bytes(b"same content")
    expected_version = hashlib.sha256(b"same content").hexdigest()
    locator = NoteLocator(vault="Vault", path="Notes/Sub/a.md")
    real_open_parent = adapters_module._open_anchored_parent

    def redirect_ancestor_before_walk(
        root_path: Path,
        relative_parent: PurePosixPath,
    ) -> tuple[int, int]:
        (tmp_path / "Notes").rename(tmp_path / "Notes-original")
        (tmp_path / "Notes").symlink_to("Other")
        return real_open_parent(root_path, relative_parent)

    monkeypatch.setattr(
        adapters_module,
        "_open_anchored_parent",
        redirect_ancestor_before_walk,
    )

    with pytest.raises(KnowledgeWriteConflict):
        adapter.write_note(
            locator,
            "stale proposal",
            expected_version=expected_version,
        )

    assert redirected.read_bytes() == b"same content"
    assert (tmp_path / "Notes-original" / "Sub" / "a.md").read_bytes() == b"same content"


def test_rewritten_write_uses_atomic_replace_at_filesystem_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/atomic.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def recording_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", recording_exchange)

    before_fds = _open_fd_count()
    receipt = adapter.write_note(
        locator,
        "replacement",
        expected_version=expected_version,
        writer_identity="mac-runtime",
    )

    assert exchanges == 1
    assert target.read_text(encoding="utf-8") == "replacement"
    assert receipt.operation == "write_note"
    assert receipt.outcome == "written"
    assert receipt.conflict_artifact is None
    assert _open_fd_count() == before_fds


def test_stale_rewritten_write_stages_conflict_artifact_at_filesystem_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/shared.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"human-current")
    stale_version = hashlib.sha256(b"caller-observed").hexdigest()
    real_stage = adapters_module._stage_initial_stale_proposal
    real_link = os.link
    racer_entry_name: str | None = None
    candidate_guard_observed = False

    def unexpected_exchange(*_args: object) -> None:
        raise AssertionError("an initially stale write must not exchange the canonical note")

    def replace_hidden_entry_before_publication(
        parent_fd: int,
        conflict_fd: int,
        staged_name: str,
        staged_locator: NoteLocator,
        *,
        payload: bytes,
        payload_version: str,
        staged_stat: os.stat_result,
        writer_identity: str,
        written_at: datetime,
    ) -> tuple[PurePosixPath, os.stat_result]:
        nonlocal racer_entry_name
        assert _has_open_file_identity(staged_stat)
        os.unlink(staged_name, dir_fd=parent_fd)
        replacement_fd = os.open(
            staged_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(replacement_fd, "wb") as replacement:
            replacement.write(b"directory-racer")
            replacement.flush()
            os.fsync(replacement.fileno())
        os.fsync(parent_fd)
        racer_entry_name = staged_name
        return real_stage(
            parent_fd,
            conflict_fd,
            staged_name,
            staged_locator,
            payload=payload,
            payload_version=payload_version,
            staged_stat=staged_stat,
            writer_identity=writer_identity,
            written_at=written_at,
        )

    def observe_candidate_guard(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal candidate_guard_observed
        if src.endswith(".conflict-stage") and src_dir_fd is not None:
            candidate_stat = os.stat(
                src,
                dir_fd=src_dir_fd,
                follow_symlinks=False,
            )
            candidate_guard_observed = _has_open_file_identity(candidate_stat)
        real_link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", unexpected_exchange)
    monkeypatch.setattr(os, "link", observe_candidate_guard)
    monkeypatch.setattr(
        adapters_module,
        "_stage_initial_stale_proposal",
        replace_hidden_entry_before_publication,
    )

    before_fds = _open_fd_count()
    receipt = adapter.write_note(
        locator,
        "caller-proposal",
        expected_version=stale_version,
        writer_identity="remote-writer",
    )

    assert receipt.outcome == "conflict_staged"
    assert receipt.conflict_artifact is not None
    assert receipt.writer_identity == "remote-writer"
    assert datetime.fromisoformat(receipt.written_at or "").tzinfo is UTC
    assert target.read_bytes() == b"human-current"
    artifact = tmp_path / receipt.conflict_artifact
    assert artifact.parent == target.parent
    assert artifact.read_bytes() == b"caller-proposal"
    assert "remote-writer" in artifact.name
    assert candidate_guard_observed
    assert racer_entry_name is not None
    assert (target.parent / racer_entry_name).read_bytes() == b"directory-racer"
    retained_cleanup = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained_cleanup) == 1
    assert all(path.read_bytes() == b"caller-proposal" for path in retained_cleanup)
    assert _open_fd_count() == before_fds


def test_cleanup_atomically_restores_replacement_injected_before_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "Notes"
    conflict = parent / "_conflicts"
    conflict.mkdir(parents=True)
    source_name = ".cleanup-race.md.rewrite-swap"
    source = parent / source_name
    source.write_bytes(b"controlled")
    parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    conflict_fd = os.open(conflict, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    guard_fd = os.open(source_name, os.O_RDONLY, dir_fd=parent_fd)
    expected = os.fstat(guard_fd)
    real_rename = adapters_module._atomic_rename_noreplace_at
    injected = False

    def replace_immediately_before_atomic_retention(
        source_dir_fd: int,
        moving_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal injected
        if not injected and source_dir_fd == parent_fd and moving_name == source_name:
            injected = True
            os.unlink(moving_name, dir_fd=source_dir_fd)
            replacement_fd = os.open(
                moving_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_dir_fd,
            )
            with os.fdopen(replacement_fd, "wb") as replacement:
                replacement.write(b"directory-racer")
                replacement.flush()
                os.fsync(replacement.fileno())
            os.fsync(source_dir_fd)
        real_rename(
            source_dir_fd,
            moving_name,
            destination_dir_fd,
            destination_name,
        )

    monkeypatch.setattr(
        adapters_module,
        "_atomic_rename_noreplace_at",
        replace_immediately_before_atomic_retention,
    )
    try:
        retained_name = adapters_module._atomically_retain_controlled_entry(
            parent_fd,
            source_name,
            expected,
            conflict_fd,
            NoteLocator(vault="Vault", path="Notes/cleanup-race.md"),
        )
    finally:
        os.close(guard_fd)
        os.close(conflict_fd)
        os.close(parent_fd)

    assert injected
    assert retained_name is None
    assert source.read_bytes() == b"directory-racer"
    assert list(conflict.iterdir()) == []


def test_cleanup_restore_collision_closes_all_adapter_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/cleanup-collision.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_rename = adapters_module._atomic_rename_noreplace_at
    injected_source: str | None = None
    restore_collision = False

    def stop_before_exchange(*_args: object, **_kwargs: object) -> None:
        raise KnowledgeWriteConflict("forced pre-exchange cleanup")

    def collide_with_cleanup_restoration(
        source_dir_fd: int,
        moving_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal injected_source, restore_collision
        if injected_source is None and moving_name.endswith(".rewrite-swap"):
            injected_source = moving_name
            os.unlink(moving_name, dir_fd=source_dir_fd)
            replacement_fd = os.open(
                moving_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_dir_fd,
            )
            with os.fdopen(replacement_fd, "wb") as replacement:
                replacement.write(b"directory-racer")
                replacement.flush()
                os.fsync(replacement.fileno())
            os.fsync(source_dir_fd)
        elif (
            injected_source is not None
            and not restore_collision
            and destination_name == injected_source
        ):
            restore_collision = True
            entrant_fd = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_dir_fd,
            )
            with os.fdopen(entrant_fd, "wb") as entrant:
                entrant.write(b"later-entrant")
                entrant.flush()
                os.fsync(entrant.fileno())
            os.fsync(destination_dir_fd)
        real_rename(
            source_dir_fd,
            moving_name,
            destination_dir_fd,
            destination_name,
        )

    monkeypatch.setattr(
        adapters_module,
        "_require_anchored_directory_identity",
        stop_before_exchange,
    )
    monkeypatch.setattr(
        adapters_module,
        "_atomic_rename_noreplace_at",
        collide_with_cleanup_restoration,
    )

    before_fds = _open_fd_count()
    with pytest.raises(KnowledgeWriteConflict, match="cleanup replacement was retained"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert _open_fd_count() == before_fds
    assert injected_source is not None
    assert restore_collision
    assert (target.parent / injected_source).read_bytes() == b"later-entrant"
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained) == 3
    assert {path.read_bytes() for path in retained} == {
        b"observed body",
        b"ENGINE",
        b"directory-racer",
    }


def test_staging_guard_dup_failure_keeps_owner_open_through_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/staging-dup-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    real_dup = os.dup
    real_retain = adapters_module._atomically_retain_controlled_entry
    retained_with_owner = False

    def fail_first_regular_dup(fd: int) -> int:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("simulated staging guard dup failure")
        return real_dup(fd)

    def observe_owner_during_retention(
        source_dir_fd: int,
        source_name: str,
        expected: os.stat_result,
        conflict_dir_fd: int,
        retained_locator: NoteLocator,
        *,
        retain_guard: bool = False,
    ):
        nonlocal retained_with_owner
        if source_name.endswith(".rewrite-swap"):
            retained_with_owner = _has_open_file_identity(expected)
        return real_retain(
            source_dir_fd,
            source_name,
            expected,
            conflict_dir_fd,
            retained_locator,
            retain_guard=retain_guard,
        )

    monkeypatch.setattr(os, "dup", fail_first_regular_dup)
    monkeypatch.setattr(
        adapters_module,
        "_atomically_retain_controlled_entry",
        observe_owner_during_retention,
    )

    before_fds = _open_fd_count()
    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(
            locator,
            "ENGINE",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert retained_with_owner
    assert _open_fd_count() == before_fds
    assert target.read_bytes() == b"observed body"
    assert not list(target.parent.glob(".*.rewrite-swap"))


def test_candidate_guard_dup_failure_keeps_owner_open_through_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/candidate-dup-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"human-current")
    real_dup = os.dup
    real_retain = adapters_module._atomically_retain_controlled_entry
    regular_dup_calls = 0
    retained_with_owner = False

    def fail_candidate_regular_dup(fd: int) -> int:
        nonlocal regular_dup_calls
        if stat.S_ISREG(os.fstat(fd).st_mode):
            regular_dup_calls += 1
            if regular_dup_calls == 3:
                raise OSError("simulated candidate guard dup failure")
        return real_dup(fd)

    def observe_owner_during_retention(
        source_dir_fd: int,
        source_name: str,
        expected: os.stat_result,
        conflict_dir_fd: int,
        retained_locator: NoteLocator,
        *,
        retain_guard: bool = False,
    ):
        nonlocal retained_with_owner
        if source_name.endswith(".conflict-stage"):
            retained_with_owner = _has_open_file_identity(expected)
        return real_retain(
            source_dir_fd,
            source_name,
            expected,
            conflict_dir_fd,
            retained_locator,
            retain_guard=retain_guard,
        )

    monkeypatch.setattr(os, "dup", fail_candidate_regular_dup)
    monkeypatch.setattr(
        adapters_module,
        "_atomically_retain_controlled_entry",
        observe_owner_during_retention,
    )

    before_fds = _open_fd_count()
    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(
            locator,
            "caller proposal",
            expected_version=hashlib.sha256(b"caller observed").hexdigest(),
        )

    assert regular_dup_calls == 3
    assert retained_with_owner
    assert _open_fd_count() == before_fds
    assert target.read_bytes() == b"human-current"
    assert not list(target.parent.glob(".*.conflict-stage"))


def test_stale_rewritten_write_retains_trusted_candidate_if_public_artifact_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/public-replacement.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"human-current")
    real_read_entry = adapters_module._read_entry
    artifact_reads = 0

    def replace_artifact_during_final_verification(dir_fd: int, name: str) -> bytes:
        nonlocal artifact_reads
        if is_conflict_artifact(name):
            artifact_reads += 1
            if artifact_reads == 2:
                os.unlink(name, dir_fd=dir_fd)
                replacement_fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=dir_fd,
                )
                with os.fdopen(replacement_fd, "wb") as replacement:
                    replacement.write(b"directory-racer")
                    replacement.flush()
                    os.fsync(replacement.fileno())
                os.fsync(dir_fd)
        return real_read_entry(dir_fd, name)

    monkeypatch.setattr(
        adapters_module,
        "_read_entry",
        replace_artifact_during_final_verification,
    )

    with pytest.raises(KnowledgeWriteConflict, match="changed before receipt"):
        adapter.write_note(
            locator,
            "caller-proposal",
            expected_version=hashlib.sha256(b"caller-observed").hexdigest(),
            writer_identity="remote-writer",
        )

    assert target.read_bytes() == b"human-current"
    trusted_candidates = list(target.parent.glob(".*.conflict-stage"))
    assert len(trusted_candidates) == 1
    assert trusted_candidates[0].read_bytes() == b"caller-proposal"


def test_stale_public_artifact_replaced_after_helper_fails_outer_receipt_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/outer-replacement.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"human-current")
    real_stage = adapters_module._stage_initial_stale_proposal
    replaced_artifact: PurePosixPath | None = None

    def replace_after_helper(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal replaced_artifact
        artifact_rel, artifact_stat = real_stage(*args, **kwargs)
        parent_fd = args[0]
        os.unlink(artifact_rel.name, dir_fd=parent_fd)
        replacement_fd = os.open(
            artifact_rel.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(replacement_fd, "wb") as replacement:
            replacement.write(b"directory-racer")
            replacement.flush()
            os.fsync(replacement.fileno())
        os.fsync(parent_fd)
        replaced_artifact = artifact_rel
        return artifact_rel, artifact_stat

    monkeypatch.setattr(
        adapters_module,
        "_stage_initial_stale_proposal",
        replace_after_helper,
    )

    with pytest.raises(KnowledgeWriteConflict, match="changed before receipt"):
        adapter.write_note(
            locator,
            "caller-proposal",
            expected_version=hashlib.sha256(b"caller-observed").hexdigest(),
        )

    assert replaced_artifact is not None
    assert (tmp_path / replaced_artifact).read_bytes() == b"directory-racer"
    assert target.read_bytes() == b"human-current"
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert b"caller-proposal" in {path.read_bytes() for path in retained}


@pytest.mark.parametrize("fault", ["write", "flush", "fsync"])
def test_rewritten_write_staging_io_failure_cleans_controlled_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/staging-io-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    before_fds = _open_fd_count()
    _install_staged_io_fault(
        monkeypatch,
        fault=fault,
        fdopen_call=1,
        regular_fsync_call=1,
    )

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(
            locator,
            "caller proposal",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert target.read_bytes() == b"observed body"
    assert list(target.parent.glob(".*.rewrite-swap")) == []
    assert list(target.parent.glob(".*.conflict-stage")) == []
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained) == 1
    assert all(path.suffix == ".conflict" for path in retained)
    assert _open_fd_count() == before_fds


@pytest.mark.parametrize("fault", ["write", "flush", "fsync"])
def test_initial_stale_candidate_io_failure_cleans_partial_and_preserves_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/candidate-io-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"human current")
    before_fds = _open_fd_count()
    _install_staged_io_fault(
        monkeypatch,
        fault=fault,
        fdopen_call=3,
        regular_fsync_call=2,
    )

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(
            locator,
            "caller proposal",
            expected_version=hashlib.sha256(b"caller observed").hexdigest(),
        )

    assert target.read_bytes() == b"human current"
    assert list(target.parent.glob(".*.rewrite-swap")) == []
    assert list(target.parent.glob(".*.conflict-stage")) == []
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained) == 2
    assert b"caller proposal" in {path.read_bytes() for path in retained}
    assert all(path.suffix == ".conflict" for path in retained)
    assert _open_fd_count() == before_fds


def test_staged_conflict_artifact_matches_quarantine_classifier(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/classified.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"current")

    receipt = adapter.write_note(
        locator,
        "stale proposal",
        expected_version=hashlib.sha256(b"stale").hexdigest(),
        writer_identity="codex-app",
    )

    assert receipt.outcome == "conflict_staged"
    assert receipt.conflict_artifact is not None
    assert is_conflict_artifact(receipt.conflict_artifact)
    retained_cleanup = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained_cleanup) == 2
    assert all(path.read_bytes() == b"stale proposal" for path in retained_cleanup)


def test_append_only_write_does_not_stage_stale_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="_heimdal/watchlist.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_text("existing\n", encoding="utf-8")

    def unexpected_version_read(_handle: object) -> bytes:
        raise AssertionError("append-only writes must not enter rewritten-note stale detection")

    monkeypatch.setattr(adapters_module, "_read_handle", unexpected_version_read)

    receipt = adapter.append_note(locator, "- appended\n")

    assert target.read_text(encoding="utf-8") == "existing\n- appended\n"
    assert receipt.operation == "append_note"
    assert receipt.note_class is NoteClass.APPEND_ONLY
    assert receipt.outcome == "written"
    assert receipt.conflict_artifact is None
    assert not any(is_conflict_artifact(path.name) for path in target.parent.iterdir())


def test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam(
    tmp_path: Path,
) -> None:
    """VMW-01 enactment-gap model (owner decision 2026-07-13): enforcement of the
    rewritten-note version guard is OPT-IN. A versionless rewrite is performed
    normally so legacy writers are never broken during progressive migration
    (#3570), while still recording the structured ``note_class`` outcome on the
    receipt. A caller that opts in with ``expected_version`` gets optimistic
    concurrency: a stale version stages the caller's proposal as a sibling
    conflict artifact without overwriting the canonical note."""
    note = tmp_path / "Notes" / "human.md"
    note.parent.mkdir(parents=True)
    note.write_text("old", encoding="utf-8")

    # Deferred enforcement: no expected_version -> the write succeeds (not a raise)
    # and the receipt still records the REWRITTEN classification.
    deferred_receipt = write_note_from_absolute(note, "new", vault_root=tmp_path)
    assert note.read_text(encoding="utf-8") == "new"
    assert deferred_receipt.note_class is NoteClass.REWRITTEN

    # Opt-in optimistic concurrency: a mismatched expected_version stages the
    # caller's proposed content and leaves the canonical note untouched.
    stale_version = hashlib.sha256(b"old").hexdigest()
    conflict_receipt = write_note_from_absolute(
        note,
        "newer",
        vault_root=tmp_path,
        expected_version=stale_version,
        writer_identity="mac-runtime",
        accept_staged_conflict=True,
    )
    assert note.read_text(encoding="utf-8") == "new"
    assert conflict_receipt.outcome == "conflict_staged"
    assert conflict_receipt.conflict_artifact is not None
    assert (tmp_path / conflict_receipt.conflict_artifact).read_text(encoding="utf-8") == "newer"

    # Opt-in with the correct current version writes and stamps writer provenance.
    current_version = hashlib.sha256(b"new").hexdigest()
    receipt = write_note_from_absolute(
        note,
        "newer",
        vault_root=tmp_path,
        expected_version=current_version,
        writer_identity="mac-runtime",
    )
    assert note.read_text(encoding="utf-8") == "newer"
    assert receipt.writer_identity == "mac-runtime"


def test_expected_version_producers_hash_the_exact_filesystem_bytes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    text_producers = {
        "app/api/routes/companion.py": 3,
        "app/chat/canvas_writer.py": 1,
        "app/episodes/assignment.py": 1,
        "app/episodes/store.py": 1,
        "app/ports/filesystem_vault_adapter.py": 1,
        "app/promotion/queue.py": 1,
        "app/services/note_update.py": 2,
        "app/services/note_uuid.py": 1,
        "app/watcher/registry.py": 1,
        "app/watcher/vault_watcher.py": 1,
    }

    assert sum(text_producers.values()) == 13
    for relative_path, expected_reads in text_producers.items():
        source = (repo_root / relative_path).read_text(encoding="utf-8")
        assert source.count("read_note_text_with_version(") >= expected_reads, relative_path
        assert "expected_version = hashlib.sha256(" not in source, relative_path
        assert "expected_version = _WRITE_GUARD.compute_version(" not in source, relative_path

    for watcher_path in (
        "app/watcher/registry.py",
        "app/watcher/vault_watcher.py",
    ):
        watcher_source = (repo_root / watcher_path).read_text(encoding="utf-8")
        assert "write_if_unchanged(" not in watcher_source, watcher_path
        assert "write_note_from_absolute(" in watcher_source, watcher_path
        assert "watcher_panel_writeback_allowed(" in watcher_source, watcher_path

    worker_source = (repo_root / "app/workers/outbox_worker.py").read_text(
        encoding="utf-8"
    )
    assert "def _write_markdown_if_changed(" not in worker_source


def test_rewritten_write_with_expected_version_conflicts_when_target_was_deleted(
    tmp_path: Path,
) -> None:
    """An expected version means the caller observed an existing rewritten note. If that note
    vanishes before the filesystem seam, recreating it would resurrect stale human state."""
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/deleted.md")
    stale_version = hashlib.sha256(b"previous body").hexdigest()

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "stale resurrection", expected_version=stale_version)

    assert not (tmp_path / locator.path).exists()


def test_rewritten_write_does_not_resurrect_target_deleted_after_adapter_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/delete-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read = adapters_module._read_handle

    def delete_after_read(handle) -> bytes:  # type: ignore[no-untyped-def]
        data = real_read(handle)
        target.unlink()
        return data

    monkeypatch.setattr(adapters_module, "_read_handle", delete_after_read)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "stale resurrection", expected_version=expected_version)

    assert not target.exists()


def test_rewritten_write_conflicts_with_same_inode_save_after_version_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/same-inode-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read = adapters_module._read_handle

    def save_after_read(handle) -> bytes:  # type: ignore[no-untyped-def]
        data = real_read(handle)
        with target.open("r+b") as concurrent:
            concurrent.seek(0)
            concurrent.write(b"HUMAN-SAVE")
            concurrent.truncate()
            concurrent.flush()
        return data

    monkeypatch.setattr(adapters_module, "_read_handle", save_after_read)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"HUMAN-SAVE"


def test_rewritten_write_preserves_nested_writers_without_recursive_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/final-read-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read = adapters_module._read_handle
    real_exchange = adapters_module._atomic_exchange_at
    reads = 0
    exchanges = 0

    def save_after_final_read(handle) -> bytes:  # type: ignore[no-untyped-def]
        nonlocal reads
        data = real_read(handle)
        reads += 1
        if reads == 2:
            with target.open("r+b") as concurrent:
                concurrent.seek(0)
                concurrent.write(b"HUMAN-AFTER-FINAL-READ")
                concurrent.truncate()
                concurrent.flush()
        return data

    def racing_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 2:
            target.unlink()
            target.write_bytes(b"THIRD-WRITER")
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
        if exchanges == 2:
            target.unlink()
            target.write_bytes(b"FOURTH-WRITER")

    monkeypatch.setattr(adapters_module, "_read_handle", save_after_final_read)
    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", racing_exchange)

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="canonical outcome is indeterminate",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert exchanges == 2
    assert target.read_bytes() == b"FOURTH-WRITER"
    conflict_contents = [
        path.read_bytes()
        for path in (target.parent / "_conflicts").rglob("*conflicted copy*")
    ]
    assert b"HUMAN-AFTER-FINAL-READ" in conflict_contents
    assert b"THIRD-WRITER" in conflict_contents
    assert b"ENGINE" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_preserves_leaf_alias_without_recursive_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/a.md")
    target = tmp_path / locator.path
    other = target.with_name("b.md")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"same content")
    other.write_bytes(b"same content")
    expected_version = hashlib.sha256(b"same content").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def alias_at_linearization(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 1:
            assert _has_open_file_identity(target.stat())
            target.unlink()
            target.symlink_to(other.name)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(
        adapters_module,
        "_atomic_exchange_at",
        alias_at_linearization,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="target changed at atomic exchange",
    ):
        adapter.write_note(
            locator,
            "stale proposal",
            expected_version=expected_version,
        )

    assert exchanges == 1
    assert not target.is_symlink()
    assert target.read_bytes() == b"stale proposal"
    assert other.read_bytes() == b"same content"
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert any(path.is_symlink() and path.readlink() == Path(other.name) for path in retained)
    assert any(not path.is_symlink() and path.read_bytes() == b"same content" for path in retained)
    assert _open_fd_count() == before_fds


def test_rewritten_write_preserves_post_exchange_writer_and_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/post-exchange-writer.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def writers_around_primary_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 1:
            target.unlink()
            target.write_bytes(b"THIRD-WRITER")
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
        if exchanges == 1:
            target.unlink()
            target.write_bytes(b"FOURTH-WRITER")

    monkeypatch.setattr(
        adapters_module,
        "_atomic_exchange_at",
        writers_around_primary_exchange,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="target changed after atomic exchange",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert exchanges == 1
    assert target.read_bytes() == b"FOURTH-WRITER"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"THIRD-WRITER" in conflict_contents
    assert b"ENGINE" in conflict_contents
    assert b"observed body" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_preserves_existing_file_mode(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/shared-mode.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    target.chmod(0o644)
    expected_version = hashlib.sha256(b"observed body").hexdigest()

    adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.stat().st_mode & 0o777 == 0o644


def test_rewritten_write_fsyncs_staged_mode_before_atomic_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/mode-durability.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    target.chmod(0o644)
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_chmod = os.chmod
    real_fsync = os.fsync
    real_exchange = adapters_module._atomic_exchange_at
    staged_mode_changed = False
    staged_mode_synced = False

    def recording_chmod(path, mode, **kwargs) -> None:  # type: ignore[no-untyped-def]
        nonlocal staged_mode_changed
        real_chmod(path, mode, **kwargs)
        if str(path).endswith(".rewrite-swap"):
            staged_mode_changed = True

    def recording_fsync(fd: int) -> None:
        nonlocal staged_mode_synced
        if staged_mode_changed and stat.S_ISREG(os.fstat(fd).st_mode):
            staged_mode_synced = True
        real_fsync(fd)

    def asserting_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        assert staged_mode_synced
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(os, "chmod", recording_chmod)
    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", asserting_exchange)

    adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.stat().st_mode & 0o777 == 0o644


def test_rewritten_write_preserves_human_save_when_rollback_exchange_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/rollback-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def failing_rollback(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 1:
            target.write_bytes(b"HUMAN-BEFORE-EXCHANGE")
            real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
            return
        raise OSError("simulated rollback exchange failure")

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", failing_rollback)

    with pytest.raises(KnowledgeWriteConflict, match="rollback"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"ENGINE"
    conflict_contents = [
        path.read_bytes()
        for path in (target.parent / "_conflicts").rglob("*conflicted copy*")
    ]
    assert b"HUMAN-BEFORE-EXCHANGE" in conflict_contents


def test_rewritten_write_conflicts_on_mode_change_at_atomic_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/mode-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    target.chmod(0o644)
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def chmod_before_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 1:
            target.chmod(0o600)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", chmod_before_exchange)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert exchanges == 2
    assert target.read_bytes() == b"observed body"
    assert target.stat().st_mode & 0o777 == 0o600
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert retained
    assert all(not path.samefile(target) for path in retained)
    retained[0].write_bytes(b"RECOVERY-EDIT")
    assert target.read_bytes() == b"observed body"


def test_rewritten_write_retains_pre_exchange_inode_for_late_stale_fd_save(
    tmp_path: Path,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/late-stale-fd.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    stale_handle = target.open("r+b")

    receipt = adapter.write_note(locator, "ENGINE", expected_version=expected_version)
    stale_handle.seek(0)
    stale_handle.write(b"HUMAN-LATE-SAVE")
    stale_handle.truncate()
    stale_handle.flush()
    stale_handle.close()

    assert receipt.operation == "write_note"
    assert target.read_bytes() == b"ENGINE"
    conflict_contents = [
        path.read_bytes()
        for path in (target.parent / "_conflicts").rglob("*conflicted copy*")
    ]
    assert b"HUMAN-LATE-SAVE" in conflict_contents


def test_rewritten_write_recovery_guard_survives_primary_artifact_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/recovery-guard.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    stale_handle = target.open("r+b")
    real_retain = adapters_module._atomically_retain_controlled_entry
    replaced_primary: str | None = None

    def replace_primary_after_guard_publication(
        source_dir_fd: int,
        source_name: str,
        expected: os.stat_result,
        conflict_dir_fd: int,
        retained_locator: NoteLocator,
        *,
        retain_guard: bool = False,
    ):
        nonlocal replaced_primary
        retained = real_retain(
            source_dir_fd,
            source_name,
            expected,
            conflict_dir_fd,
            retained_locator,
            retain_guard=retain_guard,
        )
        if retain_guard and retained is not None:
            assert retained.guard_name is not None
            original_bytes = adapters_module._read_entry(
                conflict_dir_fd,
                retained.name,
            )
            original_mode = stat.S_IMODE(
                os.stat(
                    retained.name,
                    dir_fd=conflict_dir_fd,
                    follow_symlinks=False,
                ).st_mode
            )
            os.unlink(retained.name, dir_fd=conflict_dir_fd)
            replacement_fd = os.open(
                retained.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                original_mode,
                dir_fd=conflict_dir_fd,
            )
            with os.fdopen(replacement_fd, "wb") as replacement:
                replacement.write(original_bytes)
                replacement.flush()
                os.fsync(replacement.fileno())
            os.fsync(conflict_dir_fd)
            replaced_primary = retained.name
        return retained

    monkeypatch.setattr(
        adapters_module,
        "_atomically_retain_controlled_entry",
        replace_primary_after_guard_publication,
    )

    receipt = adapter.write_note(locator, "ENGINE", expected_version=expected_version)
    stale_handle.seek(0)
    stale_handle.write(b"HUMAN-LATE-SAVE")
    stale_handle.truncate()
    stale_handle.flush()
    stale_handle.close()

    assert receipt.operation == "write_note"
    assert replaced_primary is not None
    assert target.read_bytes() == b"ENGINE"
    conflict_contents = [
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    ]
    assert b"observed body" in conflict_contents
    assert b"HUMAN-LATE-SAVE" in conflict_contents


def test_rewritten_write_snapshots_original_before_first_recovery_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/pre-guard-replacement.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    stale_handle = target.open("r+b")
    real_link_recovery = adapters_module._link_identity_recovery
    replaced = False

    def replace_before_first_guard_link(
        source_dir_fd: int,
        source_name: str,
        expected: os.stat_result,
        conflict_dir_fd: int,
        retained_locator: NoteLocator,
    ) -> str:
        nonlocal replaced
        if not replaced and source_name.endswith(".rewrite-swap"):
            replaced = True
            stale_handle.seek(0)
            stale_handle.write(b"HUMAN-LATE")
            stale_handle.truncate()
            stale_handle.flush()
            os.fsync(stale_handle.fileno())
            os.unlink(source_name, dir_fd=source_dir_fd)
            racer_fd = os.open(
                source_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_dir_fd,
            )
            with os.fdopen(racer_fd, "wb") as racer:
                racer.write(b"RACER-HIDDEN")
                racer.flush()
                os.fsync(racer.fileno())
            os.fsync(source_dir_fd)
        return real_link_recovery(
            source_dir_fd,
            source_name,
            expected,
            conflict_dir_fd,
            retained_locator,
        )

    monkeypatch.setattr(
        adapters_module,
        "_link_identity_recovery",
        replace_before_first_guard_link,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="recovery guard changed",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert replaced
    assert target.read_bytes() == b"ENGINE"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"observed body" in conflict_contents
    assert b"HUMAN-LATE" in conflict_contents
    assert b"RACER-HIDDEN" in conflict_contents
    assert _open_fd_count() == before_fds
    stale_handle.close()


def test_rewritten_write_preserves_intended_payload_after_staging_inode_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/staging-inode-mutation.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    exchanges = 0

    def mutate_staging_before_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges
        exchanges += 1
        if exchanges == 1:
            mutated_fd = os.open(
                second_name,
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=second_dir_fd,
            )
            with os.fdopen(mutated_fd, "wb") as mutated:
                mutated.write(b"MUTATED-STAGE")
                mutated.flush()
                os.fsync(mutated.fileno())
            os.fsync(second_dir_fd)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(
        adapters_module,
        "_atomic_exchange_at",
        mutate_staging_before_exchange,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="target content changed after atomic exchange",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert exchanges == 1
    assert target.read_bytes() == b"MUTATED-STAGE"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"ENGINE" in conflict_contents
    assert b"observed body" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_preserves_intended_payload_after_precondition_name_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/precondition-name-swap.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    precondition_calls = 0
    replaced_name: str | None = None

    def replace_staging_before_precondition(
        _root_fd: int,
        _root_path: Path,
        _relative_parent: PurePosixPath,
        parent_fd: int,
        _conflict_fd: int,
        _locator: NoteLocator,
    ) -> None:
        nonlocal precondition_calls, replaced_name
        precondition_calls += 1
        if precondition_calls != 1:
            return
        replaced_name = next(
            name for name in os.listdir(parent_fd) if name.endswith(".rewrite-swap")
        )
        os.unlink(replaced_name, dir_fd=parent_fd)
        racer_fd = os.open(
            replaced_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(racer_fd, "wb") as racer:
            racer.write(b"RACER-HIDDEN")
            racer.flush()
            os.fsync(racer.fileno())
        os.fsync(parent_fd)
        raise KnowledgeWriteConflict("forced safe precondition failure")

    monkeypatch.setattr(
        adapters_module,
        "_require_anchored_directory_identity",
        replace_staging_before_precondition,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="forced safe precondition failure",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert precondition_calls == 1
    assert replaced_name is not None
    assert target.read_bytes() == b"observed body"
    assert (target.parent / replaced_name).read_bytes() == b"RACER-HIDDEN"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"ENGINE" in conflict_contents
    assert b"observed body" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_snapshots_proposal_before_original_snapshot_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/original-snapshot-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    replaced_name: str | None = None

    def fail_original_snapshot_after_staging_replacement(
        _source_fd: int,
        _expected: os.stat_result,
        _conflict_dir_fd: int,
        _locator: NoteLocator,
    ) -> str:
        nonlocal replaced_name
        replaced_name = next(
            path.name
            for path in target.parent.iterdir()
            if path.name.endswith(".rewrite-swap")
        )
        os.unlink(target.parent / replaced_name)
        replacement = target.parent / replaced_name
        replacement.write_bytes(b"RACER-HIDDEN")
        with replacement.open("rb") as racer:
            os.fsync(racer.fileno())
        raise KnowledgeWriteConflict("forced original snapshot failure")

    monkeypatch.setattr(
        adapters_module,
        "_snapshot_descriptor_recovery",
        fail_original_snapshot_after_staging_replacement,
    )

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="forced original snapshot failure",
    ):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert replaced_name is not None
    assert target.read_bytes() == b"observed body"
    assert (target.parent / replaced_name).read_bytes() == b"RACER-HIDDEN"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"ENGINE" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_pre_move_replacement_keeps_guarded_displaced_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/pre-move-guard.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    stale_handle = target.open("r+b")
    real_rename = adapters_module._atomic_rename_noreplace_at
    replaced_source: str | None = None

    def replace_immediately_before_retention_move(
        source_dir_fd: int,
        moving_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal replaced_source
        if replaced_source is None and moving_name.endswith(".rewrite-swap"):
            replaced_source = moving_name
            current_mode = stat.S_IMODE(
                os.stat(
                    moving_name,
                    dir_fd=source_dir_fd,
                    follow_symlinks=False,
                ).st_mode
            )
            os.unlink(moving_name, dir_fd=source_dir_fd)
            replacement_fd = os.open(
                moving_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                current_mode,
                dir_fd=source_dir_fd,
            )
            with os.fdopen(replacement_fd, "wb") as replacement:
                replacement.write(b"observed body")
                replacement.flush()
                os.fsync(replacement.fileno())
            os.fsync(source_dir_fd)
        real_rename(
            source_dir_fd,
            moving_name,
            destination_dir_fd,
            destination_name,
        )

    monkeypatch.setattr(
        adapters_module,
        "_atomic_rename_noreplace_at",
        replace_immediately_before_retention_move,
    )

    receipt = adapter.write_note(locator, "ENGINE", expected_version=expected_version)
    stale_handle.seek(0)
    stale_handle.write(b"HUMAN-LATE-SAVE")
    stale_handle.truncate()
    stale_handle.flush()
    stale_handle.close()

    assert receipt.operation == "write_note"
    assert replaced_source is not None
    assert (target.parent / replaced_source).read_bytes() == b"observed body"
    assert target.read_bytes() == b"ENGINE"
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(retained) == 4
    late_save_recoveries = [
        path for path in retained if path.read_bytes() == b"HUMAN-LATE-SAVE"
    ]
    assert len(late_save_recoveries) == 2
    assert late_save_recoveries[0].samefile(late_save_recoveries[1])
    assert sum(path.read_bytes() == b"observed body" for path in retained) == 1
    assert sum(path.read_bytes() == b"ENGINE" for path in retained) == 1


def test_snapshot_rollback_reads_exact_descriptor_while_recovery_name_swaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/snapshot-name-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read_handle = adapters_module._read_handle
    real_retain = adapters_module._atomically_retain_controlled_entry
    real_stable_read = adapters_module._read_stable_descriptor
    handle_reads = 0
    retained_entry = None
    swapped = False

    def save_after_final_read(handle) -> bytes:  # type: ignore[no-untyped-def]
        nonlocal handle_reads
        data = real_read_handle(handle)
        handle_reads += 1
        if handle_reads == 2:
            with target.open("r+b") as concurrent:
                concurrent.seek(0)
                concurrent.write(b"HUMAN-BEFORE-EXCHANGE")
                concurrent.truncate()
                concurrent.flush()
        return data

    def capture_retained_entry(
        source_dir_fd: int,
        source_name: str,
        expected: os.stat_result,
        conflict_dir_fd: int,
        retained_locator: NoteLocator,
        *,
        retain_guard: bool = False,
    ):
        nonlocal retained_entry
        result = real_retain(
            source_dir_fd,
            source_name,
            expected,
            conflict_dir_fd,
            retained_locator,
            retain_guard=retain_guard,
        )
        if retain_guard:
            retained_entry = result
        return result

    def swap_name_around_descriptor_read(
        fd: int,
    ) -> tuple[bytes, os.stat_result]:
        nonlocal swapped
        if retained_entry is None or swapped:
            return real_stable_read(fd)
        assert retained_entry is not None
        assert retained_entry.guard_name is not None
        conflict = target.parent / "_conflicts"
        primary = conflict / retained_entry.name
        guard = conflict / retained_entry.guard_name
        original_mode = stat.S_IMODE(primary.stat().st_mode)
        primary.unlink()
        primary.write_bytes(b"RACER-SNAPSHOT")
        primary.chmod(original_mode)
        data, descriptor_stat = real_stable_read(fd)
        primary.unlink()
        os.link(guard, primary)
        swapped = True
        return data, descriptor_stat

    monkeypatch.setattr(adapters_module, "_read_handle", save_after_final_read)
    monkeypatch.setattr(
        adapters_module,
        "_atomically_retain_controlled_entry",
        capture_retained_entry,
    )
    monkeypatch.setattr(
        adapters_module,
        "_read_stable_descriptor",
        swap_name_around_descriptor_read,
    )

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert swapped
    assert target.read_bytes() == b"HUMAN-BEFORE-EXCHANGE"
    assert target.read_bytes() != b"RACER-SNAPSHOT"
    retained = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert b"HUMAN-BEFORE-EXCHANGE" in {path.read_bytes() for path in retained}


def test_snapshot_rollback_verifies_proposal_descriptor_while_name_swaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/proposal-name-race.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read_handle = adapters_module._read_handle
    real_stable_read = adapters_module._read_stable_descriptor
    real_exchange = adapters_module._atomic_exchange_at
    handle_reads = 0
    descriptor_reads = 0
    exchanges = 0
    rollback_dir_fd = -1
    rollback_name: str | None = None
    swapped = False

    def save_after_final_read(handle) -> bytes:  # type: ignore[no-untyped-def]
        nonlocal handle_reads
        data = real_read_handle(handle)
        handle_reads += 1
        if handle_reads == 2:
            with target.open("r+b") as concurrent:
                concurrent.seek(0)
                concurrent.write(b"HUMAN-BEFORE-EXCHANGE")
                concurrent.truncate()
                concurrent.flush()
        return data

    def capture_rollback_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchanges, rollback_dir_fd, rollback_name
        exchanges += 1
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
        if exchanges == 2:
            rollback_dir_fd = second_dir_fd
            rollback_name = second_name

    def swap_proposal_name_around_descriptor_read(
        fd: int,
    ) -> tuple[bytes, os.stat_result]:
        nonlocal descriptor_reads, swapped
        descriptor_reads += 1
        if descriptor_reads != 4:
            return real_stable_read(fd)
        assert rollback_dir_fd >= 0
        assert rollback_name is not None
        held_name = f".{rollback_name}.held"
        os.rename(
            rollback_name,
            held_name,
            src_dir_fd=rollback_dir_fd,
            dst_dir_fd=rollback_dir_fd,
        )
        racer_fd = os.open(
            rollback_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=rollback_dir_fd,
        )
        with os.fdopen(racer_fd, "wb") as racer:
            racer.write(b"RACER-PROPOSAL")
            racer.flush()
            os.fsync(racer.fileno())
        data, descriptor_stat = real_stable_read(fd)
        os.unlink(rollback_name, dir_fd=rollback_dir_fd)
        os.rename(
            held_name,
            rollback_name,
            src_dir_fd=rollback_dir_fd,
            dst_dir_fd=rollback_dir_fd,
        )
        os.fsync(rollback_dir_fd)
        swapped = True
        return data, descriptor_stat

    monkeypatch.setattr(adapters_module, "_read_handle", save_after_final_read)
    monkeypatch.setattr(
        adapters_module,
        "_atomic_exchange_at",
        capture_rollback_exchange,
    )
    monkeypatch.setattr(
        adapters_module,
        "_read_stable_descriptor",
        swap_proposal_name_around_descriptor_read,
    )

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert swapped
    assert descriptor_reads == 4
    assert exchanges == 2
    assert target.read_bytes() == b"HUMAN-BEFORE-EXCHANGE"
    assert target.read_bytes() != b"RACER-PROPOSAL"


def test_rewritten_write_post_exchange_read_failure_preserves_displaced_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/post-exchange-read-error.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_stable_read = adapters_module._read_stable_descriptor
    descriptor_reads = 0

    def failing_descriptor_read(fd: int) -> tuple[bytes, os.stat_result]:
        nonlocal descriptor_reads
        descriptor_reads += 1
        if descriptor_reads == 2:
            raise PermissionError("simulated displaced verification failure")
        return real_stable_read(fd)

    monkeypatch.setattr(
        adapters_module,
        "_read_stable_descriptor",
        failing_descriptor_read,
    )

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert descriptor_reads == 2
    assert target.read_bytes() == b"ENGINE"
    artifacts = list((target.parent / "_conflicts").rglob("*conflicted copy*"))
    assert artifacts
    assert b"observed body" in {path.read_bytes() for path in artifacts}


def test_rewritten_write_post_exchange_stat_failure_preserves_displaced_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/post-exchange-stat-error.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    real_stat = os.stat
    exchange_completed = False
    injected_failure = False

    def recording_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchange_completed
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
        exchange_completed = True

    def failing_post_exchange_stat(
        path: os.PathLike[str] | str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal injected_failure
        if exchange_completed and not injected_failure and path == target.name:
            injected_failure = True
            raise PermissionError("simulated post-exchange stat failure")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", recording_exchange)
    monkeypatch.setattr(os, "stat", failing_post_exchange_stat)

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert injected_failure
    assert target.read_bytes() == b"ENGINE"
    artifacts = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert {path.read_bytes() for path in artifacts} == {
        b"observed body",
        b"ENGINE",
    }


def test_finalizer_proof_read_failure_closes_fds_and_raises_write_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/finalizer-proof-error.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_exchange = adapters_module._atomic_exchange_at
    real_stat = os.stat
    real_fstat = os.fstat
    exchange_completed = False
    body_failed = False
    proof_failed = False

    def recording_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal exchange_completed
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)
        exchange_completed = True

    def fail_body_post_exchange_stat(
        path: os.PathLike[str] | str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal body_failed
        if exchange_completed and not body_failed and path == target.name:
            body_failed = True
            raise PermissionError("simulated post-exchange body proof failure")
        return real_stat(path, *args, **kwargs)

    def fail_finalizer_fstat(fd: int) -> os.stat_result:
        nonlocal proof_failed
        if body_failed and not proof_failed:
            proof_failed = True
            raise OSError("simulated finalizer proof-read failure")
        return real_fstat(fd)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", recording_exchange)
    monkeypatch.setattr(os, "stat", fail_body_post_exchange_stat)
    monkeypatch.setattr(os, "fstat", fail_finalizer_fstat)

    before_fds = _open_fd_count()
    with pytest.raises(
        KnowledgeWriteConflict,
        match="late displaced-content recovery failed",
    ) as captured:
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert body_failed
    assert proof_failed
    assert isinstance(captured.value.__cause__, OSError)
    assert target.read_bytes() == b"ENGINE"
    conflict_contents = {
        path.read_bytes()
        for path in (target.parent / "_conflicts").glob("*.md.conflict")
    }
    assert b"observed body" in conflict_contents
    assert b"ENGINE" in conflict_contents
    assert _open_fd_count() == before_fds


def test_rewritten_write_first_exchange_error_uses_knowledge_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/first-exchange-error.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()

    def failing_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        raise OSError("simulated first exchange failure")

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", failing_exchange)

    with pytest.raises(KnowledgeWriteConflict, match="atomic exchange failed"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"observed body"


def test_retained_displaced_inode_is_not_visible_to_markdown_search(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/search-isolation.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"SECRET-OLD-ONLY")
    expected_version = hashlib.sha256(b"SECRET-OLD-ONLY").hexdigest()

    adapter.write_note(locator, "CURRENT", expected_version=expected_version)

    assert adapter.search_notes("Vault", "SECRET-OLD-ONLY") == []
    artifacts = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(artifacts) == 4
    old_recoveries = [
        path for path in artifacts if path.read_bytes() == b"SECRET-OLD-ONLY"
    ]
    assert len(old_recoveries) == 3
    assert any(
        left != right and left.samefile(right)
        for left in old_recoveries
        for right in old_recoveries
    )
    assert sum(path.read_bytes() == b"CURRENT" for path in artifacts) == 1


def test_top_level_note_conflict_artifact_stays_inside_normal_vault(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    adapter = FsVaultAdapter(vault_root)
    locator = NoteLocator(vault="Vault", path="top.md")
    target = vault_root / locator.path
    target.write_bytes(b"old")

    adapter.write_note(
        locator, "new", expected_version=hashlib.sha256(b"old").hexdigest()
    )

    assert list((vault_root / "_conflicts").glob("*.md.conflict"))
    assert not (tmp_path / "_conflicts").exists()


def test_root_anchored_legacy_adapter_places_conflict_beside_actual_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "vault" / "Notes" / "legacy.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    adapter = FsVaultAdapter(Path(target.anchor))
    locator = NoteLocator(vault="Vault", path=target.as_posix().lstrip("/"))

    adapter.write_note(
        locator, "new", expected_version=hashlib.sha256(b"old").hexdigest()
    )

    assert list((target.parent / "_conflicts").glob("*.md.conflict"))


def test_conflict_directory_symlink_escape_fails_before_exchange(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault_root.mkdir()
    outside.mkdir()
    (vault_root / "_conflicts").symlink_to(outside, target_is_directory=True)
    adapter = FsVaultAdapter(vault_root)
    locator = NoteLocator(vault="Vault", path="top.md")
    target = vault_root / locator.path
    target.write_bytes(b"old")

    with pytest.raises(KnowledgeCapabilityError, match="anchored non-symlink"):
        adapter.write_note(
            locator, "new", expected_version=hashlib.sha256(b"old").hexdigest()
        )

    assert target.read_bytes() == b"old"
    assert list(outside.iterdir()) == []


def test_rewritten_write_stays_on_anchored_parent_when_path_is_swapped_to_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    notes = vault_root / "Notes"
    moved_notes = vault_root / "Notes-original"
    outside = tmp_path / "outside"
    notes.mkdir(parents=True)
    outside.mkdir()
    target = notes / "race.md"
    target.write_bytes(b"observed body")
    outside_target = outside / target.name
    outside_target.write_bytes(b"OUTSIDE")
    adapter = FsVaultAdapter(vault_root)
    locator = NoteLocator(vault="Vault", path="Notes/race.md")
    real_open_conflict_directory = adapters_module._open_conflict_directory

    def swap_parent_after_anchor(parent_fd: int) -> int:
        notes.rename(moved_notes)
        notes.symlink_to(outside, target_is_directory=True)
        return real_open_conflict_directory(parent_fd)

    monkeypatch.setattr(
        adapters_module, "_open_conflict_directory", swap_parent_after_anchor
    )

    with pytest.raises(KnowledgeWriteConflict, match="write directory changed"):
        adapter.write_note(
            locator,
            "ENGINE",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert (moved_notes / target.name).read_bytes() == b"observed body"
    assert outside_target.read_bytes() == b"OUTSIDE"
    retained = list((moved_notes / "_conflicts").glob("*.md.conflict"))
    assert len(retained) == 3
    assert {path.read_bytes() for path in retained} == {
        b"observed body",
        b"ENGINE",
    }


def test_rewritten_write_stays_on_anchored_conflict_dir_when_path_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    notes = vault_root / "Notes"
    outside = tmp_path / "outside"
    notes.mkdir(parents=True)
    outside.mkdir()
    target = notes / "race.md"
    target.write_bytes(b"observed body")
    adapter = FsVaultAdapter(vault_root)
    locator = NoteLocator(vault="Vault", path="Notes/race.md")
    real_exchange = adapters_module._atomic_exchange_at
    retained_conflicts = notes / "_conflicts-original"
    swapped = False

    def swap_conflict_dir_after_anchor(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped:
            (notes / "_conflicts").rename(retained_conflicts)
            (notes / "_conflicts").symlink_to(outside, target_is_directory=True)
            swapped = True
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(
        adapters_module, "_atomic_exchange_at", swap_conflict_dir_after_anchor
    )

    with pytest.raises(KnowledgeWriteConflict, match="write directory changed"):
        adapter.write_note(
            locator,
            "ENGINE",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert target.read_bytes() == b"ENGINE"
    assert list(retained_conflicts.glob("*.md.conflict"))
    assert list(outside.iterdir()) == []


def test_rewritten_write_never_reports_success_after_parent_moves_at_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    notes = vault_root / "Notes"
    moved_notes = tmp_path / "moved-notes"
    notes.mkdir(parents=True)
    target = notes / "race.md"
    target.write_bytes(b"observed body")
    adapter = FsVaultAdapter(vault_root)
    locator = NoteLocator(vault="Vault", path="Notes/race.md")
    real_exchange = adapters_module._atomic_exchange_at
    swapped = False

    def move_parent_at_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped:
            notes.rename(moved_notes)
            notes.mkdir()
            (notes / target.name).write_bytes(b"THIRD-WRITER")
            swapped = True
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", move_parent_at_exchange)

    with pytest.raises(KnowledgeWriteConflict, match="write directory changed"):
        adapter.write_note(
            locator,
            "ENGINE",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert (notes / target.name).read_bytes() == b"THIRD-WRITER"
    assert (moved_notes / target.name).read_bytes() == b"ENGINE"
    artifacts = list((moved_notes / "_conflicts").glob("*.md.conflict"))
    assert len(artifacts) == 4
    assert {path.read_bytes() for path in artifacts} == {
        b"observed body",
        b"ENGINE",
    }


def test_rewritten_write_fsyncs_anchored_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/durable.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    real_fsync = os.fsync
    directory_fsyncs = 0

    def recording_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    adapter.write_note(
        locator,
        "ENGINE",
        expected_version=hashlib.sha256(b"observed body").hexdigest(),
    )

    assert directory_fsyncs >= 4


def test_rewritten_write_retains_displaced_inode_when_post_exchange_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/fsync-failure.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    real_fsync = os.fsync
    directory_fsyncs = 0

    def failing_post_exchange_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 4:
                raise OSError("simulated post-exchange directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_post_exchange_fsync)

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(
            locator,
            "ENGINE",
            expected_version=hashlib.sha256(b"observed body").hexdigest(),
        )

    assert target.read_bytes() == b"ENGINE"
    artifacts = list((target.parent / "_conflicts").glob("*.md.conflict"))
    assert len(artifacts) == 4
    assert {path.read_bytes() for path in artifacts} == {
        b"observed body",
        b"ENGINE",
    }


def test_filesystem_write_receipt_carries_writer_provenance(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/provenance.md")
    receipt = adapter.write_note(locator, "body", writer_identity="mobile-runtime")
    append_receipt = adapter.append_note(locator, "\nappend")

    assert receipt.writer_identity == "mobile-runtime"
    assert append_receipt.writer_identity
    assert datetime.fromisoformat(receipt.written_at or "").tzinfo is UTC
    assert datetime.fromisoformat(append_receipt.written_at or "").tzinfo is UTC


def test_append_operation_uses_append_only_class_at_filesystem_seam(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    receipt = adapter.append_note(NoteLocator(vault="Vault", path="_heimdal/watchlist.md"), "- item\n")
    assert receipt.note_class == NoteClass.APPEND_ONLY


def test_filesystem_seam_uses_resolved_capture_note_path(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path, capture_note_rel="📥 Inbox/inbox.md")
    receipt = adapter.append_note(NoteLocator(vault="Vault", path="📥 Inbox/inbox.md"), "- item\n")
    assert receipt.note_class == NoteClass.APPEND_ONLY


def test_conflict_artifact_classifier_recognizes_staged_and_icloud_names() -> None:
    staged = conflict_artifact_path(
        "Notes/plan.md", writer_identity="mac runtime", written_at=datetime(2026, 7, 11, tzinfo=UTC)
    )
    assert is_conflict_artifact(staged)
    assert is_conflict_artifact("Notes/plan (conflicted copy from iCloud).md")
    assert not is_conflict_artifact("Notes/plan.md")
