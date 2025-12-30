from __future__ import annotations

from pathlib import Path

import yaml

from app.vault.layout import DEFAULT_ROOT_FOLDERS, SYSTEM_NOTE_TITLE, ensure_system_note, ensure_vault_layout


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def test_ensure_vault_layout_creates_note_and_defaults(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    layout = ensure_vault_layout(vault_root)

    note_path = vault_root / "⚙️ System" / "vault.layout.md"
    assert note_path.exists()
    assert (vault_root / "📥 Inbox").is_dir()
    assert (vault_root / "🛠️ Workbench").is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    frontmatter = _load_frontmatter(note_path)
    assert frontmatter.get("system_folder") == "⚙️ System"
    assert frontmatter.get("inbox_folder") == "📥 Inbox"
    assert frontmatter.get("desk_folder") == "🛠️ Workbench"
    assert frontmatter.get("root_folders") == DEFAULT_ROOT_FOLDERS


def test_ensure_system_note_created_and_idempotent(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    ensure_vault_layout(vault_root)

    note_path = ensure_system_note(vault_root, "⚙️ System")
    assert note_path.exists()
    content = note_path.read_text(encoding="utf-8")
    assert SYSTEM_NOTE_TITLE in content

    note_path.write_text("custom\n", encoding="utf-8")
    ensure_system_note(vault_root, "⚙️ System")
    assert note_path.read_text(encoding="utf-8") == "custom\n"
