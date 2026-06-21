from __future__ import annotations

from pathlib import Path

import pytest

import app.settings.watcher_settings as watcher_settings
from app.settings.watcher_settings import DEFAULT_ALLOWED_ACTIONS, load_watcher_settings

pytestmark = pytest.mark.not_pg


def test_watcher_settings_returns_empty_when_no_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no vault selected, watcher settings resolve to an empty/no-vault state.

    Slice 05B (#2384): the legacy CWD-relative ``Path("vault")`` fallback is
    removed, so settings load without reading ``./vault/@Settings/watchers.md``.
    The settings file resolves to ``None`` (no synthesized ./vault), the source
    path is empty, and the returned settings are the packaged defaults.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.chdir(tmp_path)

    # The settings file must not be synthesized from a CWD-relative ./vault.
    assert watcher_settings._settings_file(None) is None

    settings = load_watcher_settings()

    assert settings.source.path == ""
    assert settings.allowed_actions == DEFAULT_ALLOWED_ACTIONS
    assert not (tmp_path / "vault").exists()


def test_watcher_settings_set_but_missing_does_not_crash_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A set-but-missing VAULT_ROOT degrades to no settings file, not an import crash.

    The watcher settings file (``@Settings/watchers.md``) is optional tuning
    config, not a note read/write surface. The loud set-but-missing contract is
    enforced by the resolvers that read or write vault notes (and by the channel
    preflight); for this optional lookup, a missing configured root resolves the
    settings file to ``None`` so module import does not crash.
    """
    missing = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    assert watcher_settings._settings_file(None) is None
    settings = load_watcher_settings()
    assert settings.source.path == ""
    assert settings.allowed_actions == DEFAULT_ALLOWED_ACTIONS
