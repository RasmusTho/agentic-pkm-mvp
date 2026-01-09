from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from app.watcher import registry


def test_detect_inbox_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    vault = tmp_path
    (vault / "Inbox").mkdir()
    assert registry._detect_inbox_dir(vault) == "Inbox"

    (vault / "📥 Inbox").mkdir()
    assert registry._detect_inbox_dir(vault) == "📥 Inbox"

    (vault / "📥 Inbox").rmdir()
    assert registry._detect_inbox_dir(vault) == "Inbox"


def test_detect_inbox_env_override(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path
    (vault / "Inbox").mkdir()
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Custom")
    assert registry._detect_inbox_dir(vault) == "Custom"


def test_import_does_not_mutate_env(monkeypatch) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    sys.modules.pop("app.watcher.registry", None)
    registry_mod = importlib.import_module("app.watcher.registry")
    assert os.getenv("VAULT_INBOX_DIR_REL") is None
