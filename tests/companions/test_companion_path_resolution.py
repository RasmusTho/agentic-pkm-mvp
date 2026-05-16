"""
Tests for canonical companion path resolution and duplicate detection.

Issue #974: prod ingest writes duplicate companion notes in two system locations.

Covers:
- companion_path() returns exactly one canonical path for a UUID
- find_duplicate_companions() detects when both legacy and canonical paths exist
"""
from __future__ import annotations

from pathlib import Path

from app.services.companion_note import (
    CompanionNote,
    companion_path,
    find_duplicate_companions,
    write_companion,
)


def _write_layout(vault_root: Path, system_folder: str = "⚙️ System") -> None:
    layout_path = vault_root / system_folder / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        f"---\nversion: '1'\nsystem_folder: '{system_folder}'\n"
        "inbox_folder: '📥 Inbox'\ndesk_folder: '🛠️ Workbench'\n---\n",
        encoding="utf-8",
    )


def _make_companion(uuid: str) -> CompanionNote:
    return CompanionNote(
        uuid=uuid,
        source_ref=f"Notes/note-{uuid[:8]}.md",
        title="Test Note",
        content_hash="abc123",
        ingest_state="tracked",
        last_ingested="2026-05-16T00:00:00+00:00",
        created_by_instance="test",
    )


class TestCanonicalCompanionPathIsSingleSourceOfTruth:
    """AC: deterministic resolver returns exactly one canonical path."""

    def test_canonical_companion_path_is_single_source_of_truth(
        self, tmp_path: Path
    ) -> None:
        """companion_path() must return exactly one deterministic path per UUID."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
        path = companion_path(uuid, vault_root)

        # Must return a single Path (not a list)
        assert isinstance(path, Path)

        # Must be under the canonical system folder (⚙️ System), not legacy _system
        parts = path.parts
        assert "_system" not in parts, (
            f"canonical path must not use legacy _system, got: {path}"
        )
        assert "⚙️ System" in parts, (
            f"canonical path must use the layout-configured system folder, got: {path}"
        )

        # Must end with <uuid>.md
        assert path.name == f"{uuid}.md"

        # Must be deterministic: calling again returns the same path
        path2 = companion_path(uuid, vault_root)
        assert path == path2, "companion_path() must be deterministic"

    def test_canonical_path_does_not_vary_between_calls(self, tmp_path: Path) -> None:
        """Repeated calls for the same UUID and vault always produce the same path."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "11112222-3333-4444-5555-666677778888"
        paths = {companion_path(uuid, vault_root) for _ in range(5)}
        assert len(paths) == 1, "companion_path must be stable across calls"


class TestDuplicateCompanionLocationsAreDetected:
    """AC: when both legacy and canonical exist, detect duplicates."""

    def test_duplicate_companion_locations_are_detected(
        self, tmp_path: Path
    ) -> None:
        """find_duplicate_companions() finds UUIDs present in both locations."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "dddd1111-2222-3333-4444-555566667777"
        companion = _make_companion(uuid)

        # Write to canonical location
        write_companion(vault_root, companion)

        # Also write to legacy location (simulates the bug)
        legacy_path = vault_root / "_system" / "companions" / f"{uuid}.md"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            (vault_root / companion_path(uuid, vault_root)).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        duplicates = find_duplicate_companions(vault_root)
        duplicate_uuids = [d.uuid for d in duplicates]
        assert uuid in duplicate_uuids, (
            f"UUID {uuid} present in both canonical and legacy must be reported as duplicate"
        )

    def test_no_duplicate_when_only_canonical_exists(self, tmp_path: Path) -> None:
        """find_duplicate_companions() returns empty list when only canonical exists."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "eeee2222-3333-4444-5555-666677778888"
        write_companion(vault_root, _make_companion(uuid))

        duplicates = find_duplicate_companions(vault_root)
        assert duplicates == [], "no duplicates when only canonical companion exists"

    def test_no_duplicate_when_only_legacy_exists(self, tmp_path: Path) -> None:
        """find_duplicate_companions() returns empty when only legacy exists (no canonical)."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "ffff3333-4444-5555-6666-777788889999"
        legacy_path = vault_root / "_system" / "companions" / f"{uuid}.md"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            "---\nuuid: ffff3333-4444-5555-6666-777788889999\n"
            "source_ref: Notes/old.md\ntitle: Old\ncontent_hash: abc\n"
            "ingest_state: tracked\nlast_ingested: 2026-01-01T00:00:00+00:00\n"
            "created_by_instance: test\n---\n",
            encoding="utf-8",
        )

        duplicates = find_duplicate_companions(vault_root)
        assert duplicates == [], (
            "only a legacy companion (no canonical counterpart) is not a duplicate"
        )

    def test_find_duplicate_companions_is_read_only(self, tmp_path: Path) -> None:
        """find_duplicate_companions() must not delete or modify any files."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "aaaa4444-5555-6666-7777-888899990000"
        write_companion(vault_root, _make_companion(uuid))

        canonical_path = vault_root / companion_path(uuid, vault_root)
        legacy_path = vault_root / "_system" / "companions" / f"{uuid}.md"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            canonical_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

        find_duplicate_companions(vault_root)

        assert canonical_path.exists(), "canonical companion must not be deleted"
        assert legacy_path.exists(), "legacy companion must not be deleted"
