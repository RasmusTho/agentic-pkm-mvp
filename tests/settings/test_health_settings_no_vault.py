from __future__ import annotations

from pathlib import Path

import pytest

from app.settings.health_settings import HealthSettingsV1, load_health_settings

pytestmark = pytest.mark.not_pg


def test_health_settings_reports_no_vault_without_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no vault selected, health settings report a no-vault identity.

    Slice 05B (#2384): instead of falling back to a fake default ``./vault``
    root, ``load_health_settings`` reports ``vault_status="none"`` with no
    configured root, returns the packaged defaults, and reads nothing under the
    current working directory.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.chdir(tmp_path)

    result = load_health_settings()

    assert result.vault_status == "none"
    assert result.configured_vault_root is None
    assert result.settings == HealthSettingsV1.defaults()
    assert result.source.path == ""
    assert not (tmp_path / "vault").exists()


def test_health_settings_set_but_missing_reports_not_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A set-but-missing VAULT_ROOT surfaces a not_selected identity (loud, not fake root)."""
    missing = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    result = load_health_settings()

    assert result.vault_status == "not_selected"
    assert result.configured_vault_root == str(missing)


def test_health_settings_selected_vault_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Selected-vault behavior is preserved: an explicit vault reports selected."""
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")
    vault = tmp_path / "vault"
    vault.mkdir()

    result = load_health_settings(vault_root=vault)

    assert result.vault_status == "selected"
    assert result.configured_vault_root == str(vault)
    assert result.status == "missing"  # no health.md written, but vault is bound
