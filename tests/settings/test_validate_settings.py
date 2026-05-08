from __future__ import annotations

from pathlib import Path

import pytest

import app.settings.validate as validate_module
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


def test_validate_settings_flags_missing_secret_in_compiled_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime" / "settings"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "global.yaml").write_text(
        "secrets:\n  api_token: missing:API_TOKEN\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(validate_module, "COMPILED_RUNTIME_DIR", runtime_dir)

    issues = validate_settings()

    assert any(issue.code == "runtime_settings.missing_secret" for issue in issues)
