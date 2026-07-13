from __future__ import annotations

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.knowledge import adapters as adapters_module
from app.knowledge.adapters import FsVaultAdapter
from app.knowledge.contracts import NoteLocator
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge.multiwriter import NoteClass, WriteOperation, classify_note, conflict_artifact_path, is_conflict_artifact
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


def test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam(
    tmp_path: Path,
) -> None:
    """VMW-01 enactment-gap model (owner decision 2026-07-13): enforcement of the
    rewritten-note version guard is OPT-IN. A versionless rewrite is performed
    normally so legacy writers are never broken during progressive migration
    (#3570), while still recording the structured ``note_class`` outcome on the
    receipt. A caller that opts in with ``expected_version`` gets optimistic
    concurrency: a stale version is refused with ``KnowledgeWriteConflict``."""
    note = tmp_path / "Notes" / "human.md"
    note.parent.mkdir(parents=True)
    note.write_text("old", encoding="utf-8")

    # Deferred enforcement: no expected_version -> the write succeeds (not a raise)
    # and the receipt still records the REWRITTEN classification.
    deferred_receipt = write_note_from_absolute(note, "new", vault_root=tmp_path)
    assert note.read_text(encoding="utf-8") == "new"
    assert deferred_receipt.note_class is NoteClass.REWRITTEN

    # Opt-in optimistic concurrency: a mismatched expected_version DOES raise and
    # leaves the note untouched (no silent overwrite of a concurrently-changed note).
    stale_version = hashlib.sha256(b"old").hexdigest()
    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        write_note_from_absolute(note, "newer", vault_root=tmp_path, expected_version=stale_version)
    assert note.read_text(encoding="utf-8") == "new"

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

    adapter.write_note(
        locator,
        "ENGINE",
        expected_version=hashlib.sha256(b"observed body").hexdigest(),
    )

    assert (moved_notes / target.name).read_bytes() == b"ENGINE"
    assert outside_target.read_bytes() == b"OUTSIDE"
    assert list((moved_notes / "_conflicts").glob("*.md.conflict"))


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

    adapter.write_note(
        locator,
        "ENGINE",
        expected_version=hashlib.sha256(b"observed body").hexdigest(),
    )

    assert target.read_bytes() == b"ENGINE"
    assert list(retained_conflicts.glob("*.md.conflict"))
    assert list(outside.iterdir()) == []


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
