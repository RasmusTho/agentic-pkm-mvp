from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.settings.watcher_settings import load_watcher_settings, resolve_auto_exec_enabled


def _write_watchers_file(vault: Path, content: str) -> Path:
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    watcher_file = settings_dir / "watchers.md"
    watcher_file.write_text(content, encoding="utf-8")
    return watcher_file


def test_watcher_settings_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        "---\npaths:\n  index_outbox: /tmp/from-watchers.jsonl\nauto_run:\n  allowed_actions:\n    - promote.evergreen\n---\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", "/tmp/env-outbox.jsonl")

    settings = load_watcher_settings()
    assert str(settings.paths.index_outbox) == "/tmp/from-watchers.jsonl"
    assert settings.allowed_actions == ("promote.evergreen",)
    assert settings.auto_exec_default is True


def test_watcher_settings_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    watchers = _write_watchers_file(
        vault,
        "---\nauto_run:\n  allowed_actions:\n    - promote.evergreen\npaths:\n  index_outbox: /tmp/provenance-outbox.jsonl\n---\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    settings = load_watcher_settings()
    assert settings.source.path == str(watchers)
    expected_sha = hashlib.sha256(watchers.read_bytes()).hexdigest()
    assert settings.source.sha256 == expected_sha


def test_resolve_auto_exec_enabled_uses_settings_default_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        "---\nauto_run:\n  auto_exec_default: false\n---\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_AUTO_EXEC", raising=False)

    assert resolve_auto_exec_enabled(vault_root=vault) is False


def test_resolve_auto_exec_enabled_env_override_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        "---\nauto_run:\n  auto_exec_default: false\n---\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    assert resolve_auto_exec_enabled(vault_root=vault) is True
