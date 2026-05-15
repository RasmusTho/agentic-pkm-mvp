"""
TDD tests for companion note lifecycle in the ingest pipeline.

Covers:
- Placeholder-named notes (Namnlös.md, Untitled.md) do not get companion notes
- Empty notes do not get companion notes
- Notes with content and stable mtime get companion notes
- No companion is ever written under _system/
- Orphaned companion notes can be detected (not deleted)
- Renaming a note updates companion source_ref without orphaning

These tests go through the vault_alpha ingest path end-to-end.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.services.companion_note import companion_path, read_companion
from app.services.companion_eligibility import find_orphaned_companions
from app.stores import reset_store_backends


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    # Disable companion cooldown for ingest integration tests (set to 0)
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        "---\nversion: '1'\nsystem_folder: '⚙️ System'\n"
        "inbox_folder: '📥 Inbox'\ndesk_folder: '🛠️ Workbench'\n---\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Placeholder title — no companion created
# ---------------------------------------------------------------------------

class TestPlaceholderNoteNoCompanion:
    def test_namnlos_empty_note_does_not_get_companion(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note = vault_root / "Namnlös.md"
        note.write_text("", encoding="utf-8")

        run_vault_alpha_ingest_paths(vault_root, [note])
        # Ingest may still process for indexing — but companion must not be created
        companions_dir = vault_root / "⚙️ System" / "companions"
        legacy_dir = vault_root / "_system" / "companions"

        # No companion file should exist anywhere
        assert not any(companions_dir.glob("*.md")) if companions_dir.exists() else True
        assert not any(legacy_dir.glob("*.md")) if legacy_dir.exists() else True

    def test_untitled_empty_note_does_not_get_companion(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note = vault_root / "Untitled.md"
        note.write_text("", encoding="utf-8")

        run_vault_alpha_ingest_paths(vault_root, [note])
        companions_dir = vault_root / "⚙️ System" / "companions"
        legacy_dir = vault_root / "_system" / "companions"

        assert not any(companions_dir.glob("*.md")) if companions_dir.exists() else True
        assert not any(legacy_dir.glob("*.md")) if legacy_dir.exists() else True

    def test_namnlos_with_content_does_not_get_companion_due_to_placeholder_title(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """Even if Namnlös.md has content, placeholder title still blocks companion."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note = vault_root / "Namnlös.md"
        note.write_text(
            "---\ntitle: My Real Note\nuuid: aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee\n---\n"
            "This note has real content but a placeholder filename.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])
        companions_dir = vault_root / "⚙️ System" / "companions"
        legacy_dir = vault_root / "_system" / "companions"

        assert not any(companions_dir.glob("*.md")) if companions_dir.exists() else True
        assert not any(legacy_dir.glob("*.md")) if legacy_dir.exists() else True


# ---------------------------------------------------------------------------
# Real note with content gets companion (when cooldown disabled)
# ---------------------------------------------------------------------------

class TestRealNoteGetsCompanion:
    def test_note_with_content_and_cooldown_disabled_gets_companion(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "cccc3333-dddd-eeee-ffff-aaaaaaaaaaaa"
        note = vault_root / "Notes" / "My Real Note.md"
        note.parent.mkdir()
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: My Real Note\n---\n"
            "This is a note with real content.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])
        companion = read_companion(vault_root, note_uuid)
        assert companion is not None
        assert companion.source_ref == "Notes/My Real Note.md"


# ---------------------------------------------------------------------------
# No companion under _system — dual-write removed
# ---------------------------------------------------------------------------

class TestNoLegacySystemWrite:
    def test_companion_not_written_to_system_dir(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """After removing the legacy dual-write, _system/companions/ must stay empty."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "dddd4444-eeee-ffff-aaaa-bbbbbbbbbbbb"
        note = vault_root / "Notes" / "A Note.md"
        note.parent.mkdir()
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: A Note\n---\nSome content.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])

        # Canonical companion should exist
        canonical_companion = vault_root / companion_path(note_uuid, vault_root)
        assert canonical_companion.exists(), "canonical companion must be written"

        # Legacy _system companion must NOT exist (dual-write removed)
        legacy_companion = vault_root / "_system" / "companions" / f"{note_uuid}.md"
        assert not legacy_companion.exists(), (
            "_system/companions/ companion must not be written (legacy dual-write removed)"
        )


# ---------------------------------------------------------------------------
# Rename scenario — companion linkage updated without orphaning
# ---------------------------------------------------------------------------

class TestRenameUpdatesCompanion:
    def test_rename_updates_source_ref_not_orphan(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """When a note is renamed, re-ingesting the new path updates the companion source_ref."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "eeee5555-ffff-aaaa-bbbb-cccccccccccc"
        original = vault_root / "Notes" / "Original Name.md"
        original.parent.mkdir()
        original.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Original Name\n---\nContent.\n",
            encoding="utf-8",
        )

        # First ingest: creates companion at original path
        run_vault_alpha_ingest_paths(vault_root, [original])
        companion_before = read_companion(vault_root, note_uuid)
        assert companion_before is not None
        assert companion_before.source_ref == "Notes/Original Name.md"

        # Simulate rename: write to new path with same uuid
        renamed = vault_root / "Notes" / "New Name.md"
        renamed.write_text(
            f"---\nuuid: {note_uuid}\ntitle: New Name\n---\nContent.\n",
            encoding="utf-8",
        )

        # Second ingest: companion source_ref should update
        run_vault_alpha_ingest_paths(vault_root, [renamed])
        companion_after = read_companion(vault_root, note_uuid)
        assert companion_after is not None
        assert companion_after.source_ref == "Notes/New Name.md"

        # Only one companion file should exist for this uuid
        companion_dir = (vault_root / companion_path(note_uuid, vault_root)).parent
        uuid_companions = list(companion_dir.glob(f"{note_uuid}.md"))
        assert len(uuid_companions) == 1, "exactly one companion file per uuid"


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

class TestOrphanDetection:
    def test_companion_whose_source_is_missing_is_detected(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """find_orphaned_companions returns companions whose source note no longer exists."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "ffff6666-aaaa-bbbb-cccc-dddddddddddd"
        note = vault_root / "Notes" / "Ghost Note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Ghost Note\n---\nContent.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])
        companion_before = read_companion(vault_root, note_uuid)
        assert companion_before is not None

        # Delete the source note (simulates deletion or rename without re-ingest)
        note.unlink()

        # Orphan detection should find this companion
        orphans = find_orphaned_companions(vault_root)
        orphan_uuids = [o.companion.uuid for o in orphans]
        assert note_uuid in orphan_uuids

    def test_companion_with_existing_source_is_not_orphaned(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "aaaa7777-bbbb-cccc-dddd-eeeeeeeeeeee"
        note = vault_root / "Notes" / "Present Note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Present Note\n---\nContent here.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])

        orphans = find_orphaned_companions(vault_root)
        orphan_uuids = [o.companion.uuid for o in orphans]
        assert note_uuid not in orphan_uuids

    def test_orphan_detection_does_not_delete_files(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """find_orphaned_companions is report-only; it must not delete any files."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        note_uuid = "bbbb8888-cccc-dddd-eeee-ffffffffffff"
        note = vault_root / "Notes" / "Orphan Note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Orphan Note\n---\nContent.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])
        note.unlink()

        # Companion should still exist after orphan detection
        companion_file = vault_root / companion_path(note_uuid, vault_root)
        assert companion_file.exists()

        find_orphaned_companions(vault_root)

        # Still exists after detection run
        assert companion_file.exists(), "find_orphaned_companions must not delete files"
