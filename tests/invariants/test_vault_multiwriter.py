from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.knowledge.adapters import FsVaultAdapter
from app.knowledge.contracts import NoteLocator
from app.knowledge.errors import KnowledgeWriteConflict
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
    real_open = Path.open

    class _DeleteAfterRead:
        def __init__(self, handle) -> None:  # type: ignore[no-untyped-def]
            self._handle = handle

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
            self._handle.close()

        def read(self, *args):  # type: ignore[no-untyped-def]
            data = self._handle.read(*args)
            target.unlink()
            return data

        def __getattr__(self, name: str):
            return getattr(self._handle, name)

    def racing_open(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_open(path, *args, **kwargs)
        mode = kwargs.get("mode", args[0] if args else "r")
        return _DeleteAfterRead(handle) if path == target and "r" in mode else handle

    monkeypatch.setattr(Path, "open", racing_open)

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
    real_open = Path.open

    class _SaveAfterRead:
        def __init__(self, handle) -> None:  # type: ignore[no-untyped-def]
            self._handle = handle

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
            self._handle.close()

        def read(self, *args):  # type: ignore[no-untyped-def]
            data = self._handle.read(*args)
            with real_open(target, "r+b") as concurrent:
                concurrent.seek(0)
                concurrent.write(b"HUMAN-SAVE")
                concurrent.truncate()
                concurrent.flush()
            return data

        def __getattr__(self, name: str):
            return getattr(self._handle, name)

    def racing_open(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_open(path, *args, **kwargs)
        mode = kwargs.get("mode", args[0] if args else "r")
        return _SaveAfterRead(handle) if path == target and mode == "r+b" else handle

    monkeypatch.setattr(Path, "open", racing_open)

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
    real_open = Path.open
    reads = 0

    class _SaveAfterFinalRead:
        def __init__(self, handle) -> None:  # type: ignore[no-untyped-def]
            self._handle = handle

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
            self._handle.close()

        def read(self, *args):  # type: ignore[no-untyped-def]
            nonlocal reads
            data = self._handle.read(*args)
            reads += 1
            if reads == 2:
                with real_open(target, "r+b") as concurrent:
                    concurrent.seek(0)
                    concurrent.write(b"HUMAN-AFTER-FINAL-READ")
                    concurrent.truncate()
                    concurrent.flush()
            return data

        def __getattr__(self, name: str):
            return getattr(self._handle, name)

    def racing_open(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_open(path, *args, **kwargs)
        mode = kwargs.get("mode", args[0] if args else "r")
        return _SaveAfterFinalRead(handle) if path == target and mode == "r+b" else handle

    monkeypatch.setattr(Path, "open", racing_open)

    with pytest.raises(KnowledgeWriteConflict, match="version mismatch"):
        adapter.write_note(locator, "ENGINE", expected_version=expected_version)

    assert target.read_bytes() == b"HUMAN-AFTER-FINAL-READ"


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
