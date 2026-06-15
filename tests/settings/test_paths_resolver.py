from __future__ import annotations

from pathlib import Path

import pytest

from app.config.paths import (
    ResolvedPaths,
    VaultRootMisconfiguredError,
    resolve_flow_settings_path,
    resolve_optional_vault_root,
    resolve_paths,
    resolve_runtime_artifact_path,
    resolve_system_settings_path,
    resolve_vault_root,
)
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.paths import VaultPathResolver


def test_resolve_vault_root_prefers_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_root = tmp_path / "env_vault"
    monkeypatch.setenv("VAULT_ROOT", str(env_root))
    cli_root = tmp_path / "cli_vault"
    result = resolve_vault_root(cli_override=cli_root)
    assert result == cli_root


def test_resolve_vault_root_test_environment_appends_test_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    assert resolve_vault_root(environment="test") == Path("vault-test")


def test_resolve_vault_root_test_environment_honours_explicit_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_root = tmp_path / "custom_test_vault"
    monkeypatch.setenv("VAULT_ROOT_TEST", str(test_root))
    test_root.mkdir()
    assert resolve_vault_root(environment="test") == test_root


def test_set_but_missing_vault_root_raises_not_silent_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing_root))

    with pytest.raises(VaultRootMisconfiguredError) as exc_info:
        resolve_vault_root()

    assert exc_info.value.env_var == "VAULT_ROOT"
    assert exc_info.value.configured_path == missing_root


def test_unset_vault_root_resolves_to_no_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    # The capability flip: an unset VAULT_ROOT now reports an explicit no-vault
    # state (None) instead of silently defaulting to a CWD-relative ./vault.
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    assert resolve_optional_vault_root() is None
    assert resolve_optional_vault_root() != Path("vault")


def test_set_but_missing_vault_root_still_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # No #1757 regression: a configured-but-missing VAULT_ROOT must still raise
    # rather than collapse into the no-vault state.
    missing_root = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing_root))

    with pytest.raises(VaultRootMisconfiguredError) as exc_info:
        resolve_optional_vault_root()

    assert exc_info.value.env_var == "VAULT_ROOT"
    assert exc_info.value.configured_path == missing_root


def test_bound_vault_root_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real_vault = tmp_path / "real_vault"
    real_vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(real_vault))
    assert resolve_optional_vault_root() == real_vault


def test_optional_resolver_returns_none_for_no_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    # Callers can branch on the no-vault case without catching an exception.
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    resolution = resolve_optional_vault_root()
    if resolution is None:
        handled_no_vault = True
    else:
        handled_no_vault = False
    assert handled_no_vault is True


def test_resolve_runtime_artifact_path_scopes_test_environment() -> None:
    assert resolve_runtime_artifact_path(Path("tmp/index-outbox.jsonl"), environment="test") == Path("tmp-test/index-outbox.jsonl")


def test_system_settings_explicit_beats_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("foo: 1\n", encoding="utf-8")
    env_path = tmp_path / "env.yaml"
    env_path.write_text("bar: 2\n", encoding="utf-8")
    monkeypatch.setenv("SETTINGS_PATH", str(env_path))
    resolved = resolve_system_settings_path(explicit=explicit)
    assert resolved == explicit


def test_system_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_path = tmp_path / "env.yaml"
    env_path.write_text("foo: env\n", encoding="utf-8")
    monkeypatch.setenv("SETTINGS_PATH", str(env_path))
    resolved = resolve_system_settings_path()
    assert resolved == env_path


def test_system_settings_prefers_existing_vault_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SETTINGS_PATH", raising=False)
    vault_root = tmp_path / "vault"
    target = vault_root / "_system" / "settings" / "system-settings.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("foo: vault\n", encoding="utf-8")
    resolved = resolve_system_settings_path(vault_root=vault_root)
    assert resolved == target


def test_system_settings_falls_back_to_yggdrasil(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SETTINGS_PATH", raising=False)
    vault_root = tmp_path / "vault"
    ygg_root = tmp_path / "Yggdrasil"
    mimer_settings = ygg_root / "Mimer" / "@Settings" / "system-settings.yaml"
    mimer_settings.parent.mkdir(parents=True, exist_ok=True)
    mimer_settings.write_text("foo: ygg\n", encoding="utf-8")
    resolved = resolve_system_settings_path(vault_root=vault_root, yggdrasil_root=ygg_root)
    assert resolved == mimer_settings


def test_system_settings_default_path_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SETTINGS_PATH", raising=False)
    vault_root = tmp_path / "vault"
    resolved = resolve_system_settings_path(vault_root=vault_root)
    assert resolved == vault_root / "_system" / "settings" / "system-settings.yaml"


def test_flow_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_path = tmp_path / "flows.yaml"
    env_path.write_text("flows: {}\n", encoding="utf-8")
    monkeypatch.setenv("FLOW_SETTINGS_PATH", str(env_path))
    resolved = resolve_flow_settings_path()
    assert resolved == env_path


def test_flow_settings_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FLOW_SETTINGS_PATH", raising=False)
    vault_root = tmp_path / "vault"
    default_flow = vault_root / "_system" / "settings" / "flows.settings.yaml"
    default_flow.parent.mkdir(parents=True, exist_ok=True)
    default_flow.write_text("flows: {}\n", encoding="utf-8")
    resolved = resolve_flow_settings_path(vault_root=vault_root)
    assert resolved == default_flow


def test_resolve_paths_combines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    vault_root = tmp_path / "vault"
    settings_path = tmp_path / "custom" / "settings.yaml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("foo: bar\n", encoding="utf-8")
    result = resolve_paths(vault_root=vault_root, settings_path=settings_path)
    assert isinstance(result, ResolvedPaths)
    assert result.vault_root == vault_root
    assert result.system_settings_path == settings_path


def test_vault_paths_resolve_from_vault_context_settings(tmp_path: Path) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(tmp_path / "vault").context
    paths_settings = tmp_path / "vault" / "settings" / "paths.md"
    paths_settings.write_text(
        "---\n"
        "schema: design-handoff.paths.v1\n"
        "scope: vault-shared\n"
        "handoffFolder: Project Intake\n"
        "assetsFolder: Project Intake/Files\n"
        "templatesFolder: Project Intake/Templates\n"
        "archiveFolder: Project Intake/Closed\n"
        "---\n"
        "# Path Settings\n",
        encoding="utf-8",
    )

    resolved = VaultPathResolver().resolve(context)

    assert resolved.vault_root == tmp_path / "vault"
    assert resolved.settings_dir == tmp_path / "vault" / "settings"
    assert resolved.handoff_dir == tmp_path / "vault" / "Project Intake"
    assert resolved.assets_dir == tmp_path / "vault" / "Project Intake" / "Files"
    assert resolved.templates_dir == tmp_path / "vault" / "Project Intake" / "Templates"
    assert resolved.archive_dir == tmp_path / "vault" / "Project Intake" / "Closed"
