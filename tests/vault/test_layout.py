from __future__ import annotations

from pathlib import Path

import yaml

from app.vault.layout import DEFAULT_ROOT_FOLDERS, ensure_vault_layout, load_or_create_layout, normalize_md_filename


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def test_load_layout_defaults(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    layout_dir = vault_root / "⚙️ System"
    layout_dir.mkdir()
    layout_path = layout_dir / "vault.layout.md"
    layout_path.write_text(
        """---\nversion: "1"\ninbox_folder: "📥 Inbox"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    layout = load_or_create_layout(vault_root)

    assert layout.inbox_folder == "📥 Inbox"
    assert layout.desk_folder == "🛠️ Workbench"
    assert layout.system_folder == "⚙️ System"
    assert layout.include_folders is None
    assert layout.root_folders == DEFAULT_ROOT_FOLDERS
    assert layout.note_path == layout_path


def test_ensure_vault_layout_creates_note_and_folders(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    layout = ensure_vault_layout(vault_root)

    assert (vault_root / "⚙️ System" / "vault.layout.md").exists()
    assert (vault_root / layout.inbox_folder).is_dir()
    assert (vault_root / layout.desk_folder).is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    for folder in DEFAULT_ROOT_FOLDERS:
        assert (vault_root / folder).is_dir()

    layout_second = ensure_vault_layout(vault_root)
    assert layout_second == layout

    frontmatter = _load_frontmatter(vault_root / "⚙️ System" / "vault.layout.md")
    assert frontmatter.get("system_folder") == "⚙️ System"
    assert frontmatter.get("inbox_folder") == "📥 Inbox"
    assert frontmatter.get("desk_folder") == "🛠️ Workbench"
    assert frontmatter.get("root_folders") == DEFAULT_ROOT_FOLDERS


def test_normalize_md_filename_does_not_double_extension() -> None:
    assert normalize_md_filename("ingest.override.md") == "ingest.override.md"
    assert normalize_md_filename("ingest.override") == "ingest.override.md"
    assert normalize_md_filename("vault.layout.md.md") == "vault.layout.md"
