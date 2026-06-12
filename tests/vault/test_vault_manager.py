from __future__ import annotations

from pathlib import Path

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


def _manager(tmp_path: Path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


def test_initial_context_is_none_without_config(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert manager.context.status == "none"


def test_select_missing_path_gives_missing(tmp_path: Path) -> None:
    context = _manager(tmp_path).select_vault(tmp_path / "missing")

    assert context.status == "missing"
    assert context.active_vault_path == str(tmp_path / "missing")


def test_select_existing_uninitialized_folder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    context = _manager(tmp_path).select_vault(vault)

    assert context.status == "uninitialized"
    assert context.settings_path == str(vault / "settings")


def test_initialize_vault_creates_expected_settings_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    result = _manager(tmp_path).initialize_vault(vault, vault_name="Test Vault")

    assert result.context.status == "selected"
    assert result.context.active_vault_name == "Test Vault"
    expected = {
        "settings/vault.md",
        "settings/paths.md",
        "settings/workflow.md",
        "settings/design-handoff.md",
        "settings/companion-ui.md",
        "settings/local.md",
        "settings/.gitignore",
    }
    assert set(result.created_files) == expected
    for rel_path in expected:
        assert (vault / rel_path).exists()


def test_initialize_vault_creates_local_settings_gitignore(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    _manager(tmp_path).initialize_vault(vault)

    text = (vault / "settings" / ".gitignore").read_text(encoding="utf-8")
    assert "local.md" in text
    assert "*.local.md" in text
    assert "runtime/" in text
    assert "cache/" in text
    assert "*" not in {line.strip() for line in text.splitlines()}


def test_select_initialized_vault_reads_ids(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    initialized = manager.initialize_vault(vault)

    context = manager.select_vault(vault)

    assert context.status == "selected"
    assert context.active_vault_id == initialized.context.active_vault_id
    assert context.local_instance_id == initialized.context.local_instance_id


def test_conflicted_settings_mark_vault_invalid(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    manager.initialize_vault(vault)
    (vault / "settings" / "vault.md").write_text(
        "---\n<<<<<<< HEAD\nschema: design-handoff.vault.v1\n=======\nschema: other\n>>>>>>> branch\n---\n",
        encoding="utf-8",
    )

    context = manager.select_vault(vault)

    assert context.status == "invalid"
    assert "conflict markers" in str(context.validation_error)
