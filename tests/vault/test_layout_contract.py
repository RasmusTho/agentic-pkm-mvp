from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.vault.layout import LAYOUT_NOTE_NAME, SYSTEM_NOTE_TITLE, ensure_system_note, ensure_vault_layout


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def test_ensure_vault_layout_creates_note_and_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    system_folder = "⚙️ System"
    inbox_folder = "📥 Inbox"
    desk_folder = "🛠️ Workbench"

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_folder)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", inbox_folder)
    monkeypatch.setenv("VAULT_DESK_DIR_REL", desk_folder)

    layout = ensure_vault_layout(vault_root)

    note_path = vault_root / system_folder / LAYOUT_NOTE_NAME
    assert note_path.exists()
    assert (vault_root / inbox_folder).is_dir()
    assert (vault_root / desk_folder).is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    frontmatter = _load_frontmatter(note_path)
    assert frontmatter.get("system_folder") == system_folder
    assert frontmatter.get("inbox_folder") == inbox_folder
    assert frontmatter.get("desk_folder") == desk_folder
    assert frontmatter.get("root_folders") == [system_folder, inbox_folder, desk_folder]


def test_ensure_system_note_created_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    system_folder = "⚙️ System"
    inbox_folder = "📥 Inbox"
    desk_folder = "🛠️ Workbench"

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_folder)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", inbox_folder)
    monkeypatch.setenv("VAULT_DESK_DIR_REL", desk_folder)

    ensure_vault_layout(vault_root)

    note_path = ensure_system_note(vault_root, system_folder)
    assert note_path.exists()
    assert note_path.name.endswith(".md")
    assert SYSTEM_NOTE_TITLE in note_path.name

    note_path.write_text("custom\n", encoding="utf-8")
    ensure_system_note(vault_root, system_folder)
    assert note_path.read_text(encoding="utf-8") == "custom\n"
