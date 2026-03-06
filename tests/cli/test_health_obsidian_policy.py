from __future__ import annotations

import importlib

health_module = importlib.import_module("app.cli.health")


def test_obsidian_required_false_when_non_strict_fallback_allowed(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "0")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "1")
    assert health_module._obsidian_required() is False


def test_obsidian_required_true_when_strict(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "1")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
    assert health_module._obsidian_required() is True


def test_get_obsidian_installer_version_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("OBSIDIAN_INSTALLER_VERSION", "1.12.4")
    assert health_module._get_obsidian_installer_version() == "1.12.4"


def test_check_obsidian_dependencies_passes_installer_reader(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "obsidian_cli")
    monkeypatch.setenv("KNOWLEDGE_FALLBACK_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "1")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
    monkeypatch.setenv("OBSIDIAN_INSTALLER_VERSION", "1.12.4")

    class _Status:
        ok = True
        details = {"required_installer": "1.12.4"}

    captured: dict[str, str] = {}

    def fake_status(*, get_installer_version=None, **kwargs):  # type: ignore[no-untyped-def]
        assert callable(get_installer_version)
        captured["version"] = str(get_installer_version())
        return _Status()

    monkeypatch.setattr("app.cli.health.obsidian_dependency_status", fake_status)
    result = health_module._check_obsidian_dependencies()
    assert result["ok"] is True
    assert captured["version"] == "1.12.4"
