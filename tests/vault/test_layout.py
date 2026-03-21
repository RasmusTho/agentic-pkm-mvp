from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.vault.layout import LAYOUT_NOTE_NAME, ensure_vault_layout, load_layout, normalize_md_filename


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) if len(parts) > 2 else {}


def _write_layout_note(path: Path, *, system_folder: str, inbox_folder: str, desk_folder: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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


def test_load_layout_reads_required_fields(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    system_folder = "⚙️ System"
    inbox_folder = "📥 Inbox"
    desk_folder = "🛠️ Workbench"

    layout_path = vault_root / system_folder / LAYOUT_NOTE_NAME
    _write_layout_note(
        layout_path,
        system_folder=system_folder,
        inbox_folder=inbox_folder,
        desk_folder=desk_folder,
    )

    layout = load_layout(vault_root)

    assert layout.inbox_folder == inbox_folder
    assert layout.desk_folder == desk_folder
    assert layout.system_folder == system_folder
    assert layout.root_folders == [system_folder, inbox_folder, desk_folder]
    assert layout.note_path == layout_path


def test_load_layout_disambiguates_multiple_by_system_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    a = "A"
    b = "B"

    layout_a = vault_root / a / LAYOUT_NOTE_NAME
    layout_b = vault_root / b / LAYOUT_NOTE_NAME

    _write_layout_note(layout_a, system_folder=a, inbox_folder="Inbox-A", desk_folder="Desk-A")
    _write_layout_note(layout_b, system_folder=b, inbox_folder="Inbox-B", desk_folder="Desk-B")

    settings_path = vault_root / "_system" / "settings" / "system-settings.yaml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        yaml.safe_dump({"paths": {"system_dir_rel": b}}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    layout = load_layout(vault_root)
    assert layout.note_path == layout_b
    assert layout.system_folder == b
    assert layout.inbox_folder == "Inbox-B"


def test_load_layout_ignores_invalid_frontmatter_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    bad_dir = vault_root / "bad"
    bad_dir.mkdir(parents=True)
    bad_note = bad_dir / LAYOUT_NOTE_NAME
    bad_note.write_text(
        "---\n"
        "system_folder: bad\n"
        "inbox_folder: bad\n"
        "desk_folder: bad\n"
        "ignore_glob:\n"
        "  - [\n"
        "---\n",
        encoding="utf-8",
    )

    good_dir = vault_root / "good"
    good_note = good_dir / LAYOUT_NOTE_NAME
    _write_layout_note(good_note, system_folder="good", inbox_folder="Inbox", desk_folder="Desk")

    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    layout = load_layout(vault_root)
    assert layout.note_path == good_note
    assert layout.system_folder == "good"


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


def test_ensure_vault_layout_can_bootstrap_from_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    settings_dir = vault_root / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "system-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "layout": {
                    "system_folder": "⚙️ System",
                    "inbox_folder": "📥 Inbox",
                    "desk_folder": "🛠️ Workbench",
                    "runtime_dir_rel": "⚙️ System/Runtime/Alpha",
                    "root_folders": ["⚙️ System", "📥 Inbox", "🛠️ Workbench"],
                    "include_folders": ["📥 Inbox", "🛠️ Workbench"],
                },
                "paths": {
                    "system_dir_rel": "⚙️ System",
                    "inbox_dir_rel": "📥 Inbox",
                    "runtime_dir_rel": "⚙️ System/Runtime/Alpha",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_DESK_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)

    layout = ensure_vault_layout(vault_root)

    assert layout.system_folder == "⚙️ System"
    assert layout.inbox_folder == "📥 Inbox"
    assert layout.desk_folder == "🛠️ Workbench"
    assert layout.runtime_dir_rel == "⚙️ System/Runtime/Alpha"
    assert layout.root_folders == ["⚙️ System", "📥 Inbox", "🛠️ Workbench"]
    assert layout.include_folders == ["📥 Inbox", "🛠️ Workbench"]


def test_ensure_vault_layout_does_not_fallback_to_other_vault_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_vault = tmp_path / "target-vault"
    target_vault.mkdir()

    ygg_root = tmp_path / "Yggdrasil"
    settings_dir = ygg_root / "Mimer" / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "system-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "layout": {
                    "system_folder": "⚙️ System",
                    "inbox_folder": "📥 Inbox",
                    "desk_folder": "🛠️ Workbench",
                },
                "paths": {
                    "system_dir_rel": "⚙️ System",
                    "inbox_dir_rel": "📥 Inbox",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("YGGDRASIL_ROOT", str(ygg_root))
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_DESK_DIR_REL", raising=False)

    with pytest.raises(ValueError):
        ensure_vault_layout(target_vault)


def test_normalize_md_filename_does_not_double_extension() -> None:
    assert normalize_md_filename("ingest.override.md") == "ingest.override.md"
    assert normalize_md_filename("ingest.override") == "ingest.override.md"
    assert normalize_md_filename("vault.layout.md.md") == "vault.layout.md"
