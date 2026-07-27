from __future__ import annotations

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

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
    racer_entry_name: str | None = None

    def unexpected_exchange(*_args: object) -> None:
        raise AssertionError("an initially stale write must not exchange the canonical note")

    def replace_hidden_entry_before_publication(
        parent_fd: int,
        staged_name: str,
        staged_locator: NoteLocator,
        *,
        payload: bytes,
        payload_version: str,
        staged_stat: os.stat_result,
        writer_identity: str,
        written_at: datetime,
    ) -> PurePosixPath:
        nonlocal racer_entry_name
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
            staged_name,
            staged_locator,
            payload=payload,
            payload_version=payload_version,
            staged_stat=staged_stat,
            writer_identity=writer_identity,
            written_at=written_at,
        )

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", unexpected_exchange)
    monkeypatch.setattr(
        adapters_module,
        "_stage_initial_stale_proposal",
        replace_hidden_entry_before_publication,
    )

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
    assert racer_entry_name is not None
    assert (target.parent / racer_entry_name).read_bytes() == b"directory-racer"


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


def test_rewritten_write_rolls_back_same_inode_save_after_final_version_read(
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
            target.write_bytes(b"THIRD-WRITER")
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(adapters_module, "_read_handle", save_after_final_read)
    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", racing_exchange)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"HUMAN-AFTER-FINAL-READ"
    conflict_contents = [
        path.read_bytes()
        for path in (target.parent / "_conflicts").rglob("*conflicted copy*")
    ]
    assert b"THIRD-WRITER" in conflict_contents


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

    def chmod_before_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        target.chmod(0o600)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(adapters_module, "_atomic_exchange_at", chmod_before_exchange)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"observed body"
    assert target.stat().st_mode & 0o777 == 0o600


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


def test_rewritten_write_post_exchange_read_failure_preserves_displaced_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="Vault", path="Notes/post-exchange-read-error.md")
    target = tmp_path / locator.path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"observed body")
    expected_version = hashlib.sha256(b"observed body").hexdigest()
    real_read_entry = adapters_module._read_entry

    def failing_artifact_read(dir_fd: int, name: str) -> bytes:
        if "conflicted copy" in name:
            raise PermissionError("simulated displaced verification failure")
        return real_read_entry(dir_fd, name)

    monkeypatch.setattr(adapters_module, "_read_entry", failing_artifact_read)

    with pytest.raises(KnowledgeWriteConflict, match="verification failed"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"ENGINE"
    artifacts = list((target.parent / "_conflicts").rglob("*conflicted copy*"))
    assert artifacts
    assert artifacts[0].read_bytes() == b"observed body"


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
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"SECRET-OLD-ONLY"


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
    assert not list((moved_notes / "_conflicts").glob("*.md.conflict"))


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
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"observed body"


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
            if directory_fsyncs == 2:
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
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"observed body"


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
