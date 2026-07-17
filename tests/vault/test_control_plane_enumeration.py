from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.manager import iter_vault_markdown_files


def test_configured_legacy_settings_are_excluded_from_vault_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "Meta")
    system_root = tmp_path / "Meta"
    system_root.mkdir()
    (system_root / "vault.layout.md").write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    override = system_root / "settings" / "ingest.override.md"
    override.parent.mkdir()
    override.write_text("---\ninclude_folders: [Notes]\n---\n", encoding="utf-8")
    human_note = tmp_path / "Notes" / "kept.md"
    human_note.parent.mkdir()
    human_note.write_text("# Kept\n", encoding="utf-8")

    enumerated = set(iter_vault_markdown_files(tmp_path))

    assert human_note in enumerated
    assert override not in enumerated
