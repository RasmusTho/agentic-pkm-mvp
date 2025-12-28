from __future__ import annotations

from pathlib import Path

import yaml

from app.vault.layout import ensure_vault_layout


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def test_ensure_vault_layout_creates_note_and_defaults(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    layout = ensure_vault_layout(vault_root)

    note_path = vault_root / "~system" / "vault.layout.md"
    assert note_path.exists()
    assert (vault_root / "@Inbox").is_dir()
    assert (vault_root / "@Desk").is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    frontmatter = _load_frontmatter(note_path)
    assert frontmatter.get("system_folder") == "~system"
    assert frontmatter.get("inbox_folder") == "@Inbox"
    assert frontmatter.get("desk_folder") == "@Desk"
