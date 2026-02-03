from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.vault.layout import LAYOUT_NOTE_NAME, ensure_vault_layout, load_layout, normalize_md_filename


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def test_load_layout_reads_required_fields(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    system_folder = "⚙️ System"
    inbox_folder = "📥 Inbox"
    desk_folder = "🛠️ Workbench"

    layout_dir = vault_root / system_folder
    layout_dir.mkdir(parents=True)
    layout_path = layout_dir / LAYOUT_NOTE_NAME
    layout_path.write_text(
        "---\n"
        "version: '1'\n"
        f"system_folder: '{system_folder}'\n"
        f"inbox_folder: '{inbox_folder}'\n"
        f"desk_folder: '{desk_folder}'\n"
        "root_folders:\n"
        f"  - '{system_folder}'\n"
        f"  - '{inbox_folder}'\n"
        f"  - '{desk_folder}'\n"
        "---\n\nLayout note.\n",
        encoding="utf-8",
    )

    layout = load_layout(vault_root)

    assert layout.inbox_folder == inbox_folder
    assert layout.desk_folder == desk_folder
    assert layout.system_folder == system_folder
    assert layout.root_folders == [system_folder, inbox_folder, desk_folder]
    assert layout.note_path == layout_path


def test_ensure_vault_layout_creates_note_and_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    system_folder = "⚙️ System"
    inbox_folder = "📥 Inbox"
    desk_folder = "🛠️ Workbench"

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_folder)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", inbox_folder)
    monkeypatch.setenv("VAULT_DESK_DIR_REL", desk_folder)

    layout = ensure_vault_layout(vault_root)

    assert layout.system_folder == system_folder
    assert layout.inbox_folder == inbox_folder
    assert layout.desk_folder == desk_folder

    assert (vault_root / system_folder / LAYOUT_NOTE_NAME).exists()
    assert (vault_root / layout.inbox_folder).is_dir()
    assert (vault_root / layout.desk_folder).is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    layout_second = ensure_vault_layout(vault_root)
    assert layout_second == layout

    frontmatter = _load_frontmatter(vault_root / system_folder / LAYOUT_NOTE_NAME)
    assert frontmatter.get("system_folder") == system_folder
    assert frontmatter.get("inbox_folder") == inbox_folder
    assert frontmatter.get("desk_folder") == desk_folder
    assert frontmatter.get("root_folders") == [system_folder, inbox_folder, desk_folder]


def test_normalize_md_filename_does_not_double_extension() -> None:
    assert normalize_md_filename("ingest.override.md") == "ingest.override.md"
    assert normalize_md_filename("ingest.override") == "ingest.override.md"
    assert normalize_md_filename("vault.layout.md.md") == "vault.layout.md"
