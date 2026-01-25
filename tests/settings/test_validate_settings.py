from __future__ import annotations

from pathlib import Path

import pytest

from app.settings.validate import validate_settings


def _write_watchers_file(vault: Path, content: str) -> None:
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text(content, encoding="utf-8")


def test_validate_settings_includes_watcher_unknown_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        "---\nauto_run:\n  allowed_actions:\n    - unknown.action\n---\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    issues = validate_settings()
    assert any(issue.code == "watcher_settings.unknown_action" for issue in issues)
