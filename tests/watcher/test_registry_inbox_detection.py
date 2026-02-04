from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import yaml

from app.vault.layout import LAYOUT_NOTE_NAME
from app.watcher import registry


def _write_layout_note(vault: Path, inbox: str, *, system_folder: str = "⚙️ System") -> None:
    system_dir = vault / system_folder
    system_dir.mkdir(parents=True, exist_ok=True)
    note_path = system_dir / LAYOUT_NOTE_NAME
    frontmatter = {
        "version": "1",
        "system_folder": system_folder,
        "inbox_folder": inbox,
        "desk_folder": "🛠️ Workbench",
        "root_folders": [system_folder, inbox, "🛠️ Workbench"],
        "include_folders": [],
        "ignore_glob": [],
    }
    body = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---\n"
    note_path.write_text(body, encoding="utf-8")


def test_detect_inbox_from_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    _write_layout_note(tmp_path, "Custom Inbox")
    assert registry._detect_inbox_dir(tmp_path) == "Custom Inbox"


def test_detect_inbox_ignores_other_folders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    _write_layout_note(tmp_path, "Safe Inbox")
    (tmp_path / "Inbox").mkdir()
    (tmp_path / "📥 Inbox").mkdir()
    assert registry._detect_inbox_dir(tmp_path) == "Safe Inbox"


def test_detect_inbox_env_override(tmp_path: Path, monkeypatch) -> None:
    _write_layout_note(tmp_path, "Safe Inbox")
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Custom")
    assert registry._detect_inbox_dir(tmp_path) == "Custom"


def test_default_scope_glob_from_layout(tmp_path: Path, monkeypatch) -> None:
    _write_layout_note(tmp_path, "Only Inbox")
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("WATCHER_SCOPE_GLOB", raising=False)

    scope, source, inbox_source = registry._resolve_scope_glob(tmp_path)
    assert scope == "Only Inbox/**"
    assert source == "vault_layout"
    assert inbox_source == "vault_layout"


def test_import_does_not_mutate_env(monkeypatch) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    sys.modules.pop("app.watcher.registry", None)
    importlib.import_module("app.watcher.registry")
    assert os.getenv("VAULT_INBOX_DIR_REL") is None
