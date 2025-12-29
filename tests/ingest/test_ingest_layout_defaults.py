from __future__ import annotations

from pathlib import Path

from app.ingest.config import resolve_ingest_config


def test_ingest_defaults_use_layout_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    layout_dir = vault_root / "⚙️ System"
    layout_dir.mkdir(parents=True)
    layout_path = layout_dir / "vault.layout.md"
    layout_path.write_text(
        """---\ninclude_folders:\n  - "📥 Inbox"\n  - "🛠️ Workbench"\nignore_glob:\n  - "Legacy/**"\nsystem_folder: "⚙️ System"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    config = resolve_ingest_config(vault_root)

    assert config.include_folders == ["📥 Inbox", "🛠️ Workbench"]
    assert "Legacy/**" in config.ignore_glob
    assert ".obsidian/**" in config.ignore_glob
    assert ".trash/**" in config.ignore_glob
    assert "System/Metadata/VaultMirror/**" in config.ignore_glob
    assert "⚙️ System/**" not in config.ignore_glob
    assert "⚙️ System/vault.layout.md" not in config.ignore_glob
