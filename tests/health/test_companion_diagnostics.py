"""
Tests that the health/diagnostics surface reports duplicate companion notes.

Issue #974: prod ingest writes duplicate companion notes in two system locations.

The health surface must expose duplicate companions so operators can act on them.
"""
from __future__ import annotations

from pathlib import Path

from app.services.companion_note import (
    CompanionNote,
    companion_path,
    write_companion,
)
from app.services.companion_diagnostics import companion_diagnostics_summary


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


class TestDuplicateCompanionsAreReported:
    def test_duplicate_companions_are_reported(self, tmp_path: Path) -> None:
        """companion_diagnostics_summary() reports duplicates in its output."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "dddd7777-8888-9999-aaaa-bbbbccccdddd"
        companion = _make_companion(uuid)

        # Write canonical companion
        write_companion(vault_root, companion)

        # Inject legacy duplicate (simulates the bug)
        legacy_path = vault_root / "_system" / "companions" / f"{uuid}.md"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            (vault_root / companion_path(uuid, vault_root)).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        summary = companion_diagnostics_summary(vault_root)

        assert summary["duplicate_companion_count"] > 0, (
            "health summary must report at least one duplicate"
        )
        assert uuid in summary["duplicate_companion_uuids"], (
            f"UUID {uuid} must appear in duplicate_companion_uuids"
        )

    def test_no_duplicates_reported_on_clean_vault(self, tmp_path: Path) -> None:
        """companion_diagnostics_summary() reports zero duplicates on a clean vault."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "eeee8888-9999-aaaa-bbbb-ccccddddeeee"
        write_companion(vault_root, _make_companion(uuid))

        summary = companion_diagnostics_summary(vault_root)

        assert summary["duplicate_companion_count"] == 0
        assert summary["duplicate_companion_uuids"] == []
