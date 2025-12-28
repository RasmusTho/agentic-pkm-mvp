from __future__ import annotations

from pathlib import Path

from app.vault.layout import _normalize_md_name, ensure_vault_layout, load_vault_layout


def test_load_vault_layout_defaults(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    layout_path = vault_root / ".yggdrasil.md"
    layout_path.write_text(
        """---\nversion: "1"\ninbox_folder: "@Inbox"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    layout = load_vault_layout(vault_root)

    assert layout.inbox_folder == "@Inbox"
    assert layout.desk_folder == "@Desk"
    assert layout.system_folder == "~system"
    assert layout.ingest_include_folders == ["@Inbox", "@Desk"]


def test_ensure_vault_layout_creates_note_and_folders(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    layout = ensure_vault_layout(vault_root)

    assert (vault_root / ".yggdrasil.md").exists()
    assert (vault_root / layout.inbox_folder).is_dir()
    assert (vault_root / layout.desk_folder).is_dir()
    assert (vault_root / layout.system_folder).is_dir()

    layout_second = ensure_vault_layout(vault_root)
    assert layout_second == layout


def test_ensure_vault_layout_migrates_legacy_system(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    legacy_system = vault_root / "System"
    legacy_system.mkdir(parents=True)
    (legacy_system / "Legacy.md").write_text("Legacy", encoding="utf-8")

    layout = ensure_vault_layout(vault_root)

    target = vault_root / layout.system_folder / "Legacy.md"
    assert target.exists()
    assert not legacy_system.exists()


def test_normalize_md_name_does_not_double_extension() -> None:
    assert _normalize_md_name("ingest.override.md") == "ingest.override.md"
    assert _normalize_md_name("ingest.override") == "ingest.override.md"
