from __future__ import annotations

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager, no_vault_context
from app.vault.paths import VaultPathResolver
from app.vault.settings_service import SettingsService


def test_missing_settings_fall_back_to_defaults() -> None:
    effective = SettingsService().effective_settings(no_vault_context())

    assert effective["handoffFolder"].value == "Design Handoff"
    assert effective["handoffFolder"].source == "built-in"


def test_invalid_settings_returns_validation_error_and_defaults(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    paths = tmp_path / "vault" / "settings" / "paths.md"
    paths.write_text("---\nhandoffFolder: [unterminated\n---\n", encoding="utf-8")

    result = SettingsService().resolve(context)

    assert result.settings["handoffFolder"].value == "Design Handoff"
    assert result.settings["handoffFolder"].source == "built-in"
    assert len(result.validation_errors) == 1
    assert "YAML is invalid" in result.validation_errors[0].message
    assert result.validation_errors[0].source_file == str(paths)


def test_reload_reflects_external_markdown_edit(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    service = SettingsService()
    paths = tmp_path / "vault" / "settings" / "paths.md"

    first = service.reload(context)
    assert first.settings["handoffFolder"].value == "Design Handoff"

    text = paths.read_text(encoding="utf-8")
    paths.write_text(text.replace("handoffFolder: Design Handoff", "handoffFolder: External Handoff"), encoding="utf-8")

    reloaded = service.reload(context)

    assert reloaded.settings["handoffFolder"].value == "External Handoff"
    assert reloaded.settings["handoffFolder"].source_file == str(paths)
    assert reloaded.validation_errors == ()
    assert "# Path Settings" in paths.read_text(encoding="utf-8")


def test_conflicted_settings_returns_validation_error_and_defaults(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    paths = tmp_path / "vault" / "settings" / "paths.md"
    paths.write_text(
        "---\n<<<<<<< HEAD\nhandoffFolder: Mine\n=======\nhandoffFolder: Theirs\n>>>>>>> branch\n---\n",
        encoding="utf-8",
    )

    result = SettingsService().resolve(context)

    assert result.settings["handoffFolder"].value == "Design Handoff"
    assert result.settings["handoffFolder"].source == "built-in"
    assert len(result.validation_errors) == 1
    assert "conflict markers" in result.validation_errors[0].message
    assert result.validation_errors[0].source_file == str(paths)


def test_effective_settings_report_sources(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    paths = tmp_path / "vault" / "settings" / "paths.md"

    effective = SettingsService().effective_settings(context)

    assert effective["handoffFolder"].value == "Design Handoff"
    assert effective["handoffFolder"].scope == "vault-shared"
    assert effective["handoffFolder"].source == str(paths)


def test_runtime_overrides_win_last(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context

    effective = SettingsService(runtime_overrides={"handoffFolder": "Runtime Handoff"}).effective_settings(context)

    assert effective["handoffFolder"].value == "Runtime Handoff"
    assert effective["handoffFolder"].scope == "runtime"
    assert effective["handoffFolder"].source == "runtime"


def test_vault_local_settings_override_shared_settings(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    local = tmp_path / "vault" / "settings" / "local.md"
    text = local.read_text(encoding="utf-8")
    local.write_text(
        text.replace("localExportPath: null", "localExportPath: null\nhandoffFolder: Local Handoff"),
        encoding="utf-8",
    )

    effective = SettingsService().effective_settings(context)

    assert effective["handoffFolder"].value == "Local Handoff"
    assert effective["handoffFolder"].scope == "vault-local"
    assert effective["handoffFolder"].source == str(local)


def test_app_local_settings_cannot_override_vault_project_behavior(tmp_path) -> None:
    app_local = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local))
    context = manager.initialize_vault(tmp_path / "vault").context
    app_local.write_text(
        "---\n"
        "schema: design-handoff.app-local.v1\n"
        "scope: app-local\n"
        "appInstallId: app-test\n"
        "handoffFolder: App Local Handoff\n"
        "---\n",
        encoding="utf-8",
    )

    effective = SettingsService(app_local_store=AppLocalSettingsStore(app_local)).effective_settings(context)

    assert effective["appInstallId"].value == "app-test"
    assert effective["appInstallId"].scope == "app-local"
    assert effective["handoffFolder"].value == "Design Handoff"
    assert effective["handoffFolder"].scope == "vault-shared"


def test_settings_change_updates_path_resolver(tmp_path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    service = SettingsService()
    resolver = VaultPathResolver(service)

    initial = resolver.resolve(context)
    assert initial.handoff_dir == tmp_path / "vault" / "Design Handoff"

    service.update_setting(context, "handoffFolder", "Client Projects")

    updated = resolver.resolve(context)
    assert updated.handoff_dir == tmp_path / "vault" / "Client Projects"
