"""VaultManager selection persistence at the dormant settings-rebind seam."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.instance.settings_rebind import _install_dormant_settings_rebind
from app.instance.vault_registry import KnownVaultRef
from tests._mvr_default_vault_harness import active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault
from tests.integration.test_watcher_cross_process_rebind import (
    _fixture,
    _record_reload,
)

pytestmark = pytest.mark.not_pg


def test_dormant_rebind_selection_remembers_and_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A remembered picker switch survives a fresh manager restore."""

    runtime, vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    app_local_path = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))

    # Establish an existing remembered reference, then exercise the normal
    # remembered selection through the production rebind path.
    assert manager.select_vault(vault_a, remember=True).status == "selected"
    selected = manager.select_vault(vault_b, remember=True)

    assert selected.status == "selected"
    settings = AppLocalSettingsStore(app_local_path).load()
    assert settings.last_active_vault_ref == f"path:{vault_b}"
    assert set(settings.known_vaults) == {f"path:{vault_a}", f"path:{vault_b}"}
    assert runtime.registry.load().settings_rebind is not None

    restarted = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    restored = restarted.load_last_active()

    assert restored.status == "selected"
    assert restored.active_vault_path == str(vault_b)


def test_rebind_selection_without_remember_preserves_scalar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    app_local_path = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    manager.select_vault(vault_a, remember=True)

    manager.select_vault(vault_b, remember=False)

    settings = AppLocalSettingsStore(app_local_path).load()
    assert settings.last_active_vault_ref == f"path:{vault_a}"
    assert set(settings.known_vaults) == {f"path:{vault_a}"}
    assert runtime.registry.load().settings_rebind is not None


def test_active_rebind_selection_does_not_write_legacy_scalar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, extras = active_runtime(tmp_path)
    second = extras[0] if extras else None
    if second is None:
        second_root = tmp_path / "two"
        second_root.mkdir()
        second = runtime.production_register(second_root, producer="api")
    initialize_test_vault(Path(first.path))
    initialize_test_vault(Path(second.path))
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )

    app_local_path = tmp_path / "app-local.md"
    legacy = AppLocalSettingsStore(app_local_path)
    legacy.upsert_known_vault(
        KnownVaultRef(
            ref=first.ref,
            path=first.path,
            vault_id=first.vault_id,
            local_instance_id=first.local_instance_id,
            vault_name="first",
        ),
        make_active=True,
    )
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))

    manager.select_vault(Path(second.path), remember=True)

    scalar = AppLocalSettingsStore(app_local_path).load()
    assert scalar.last_active_vault_ref == first.ref
    assert set(scalar.known_vaults) == {first.ref}
    assert runtime.registry.load().last_active_vault_ref == second.ref


def test_failed_rebind_does_not_remember_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    app_local_path = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    manager.select_vault(vault_a, remember=True)

    def fail_rebind(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated rebind failure")

    monkeypatch.setattr(
        "app.instance.settings_rebind.SettingsRebindActivation.activate",
        fail_rebind,
    )

    with pytest.raises(RuntimeError, match="simulated rebind failure"):
        manager.select_vault(vault_b, remember=True)

    settings = AppLocalSettingsStore(app_local_path).load()
    assert settings.last_active_vault_ref == f"path:{vault_a}"
    assert set(settings.known_vaults) == {f"path:{vault_a}"}
    assert runtime.registry.load().last_active_vault_ref is None
    assert manager.context.active_vault_path == str(vault_a)


def test_remember_persistence_failure_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    app_local_path = tmp_path / "app-local.md"
    app_local_store = AppLocalSettingsStore(app_local_path)
    manager = VaultManager(app_local_store=app_local_store)
    manager.select_vault(vault_a, remember=True)

    def fail_remember(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated app-local persistence failure")

    monkeypatch.setattr(app_local_store, "upsert_known_vault", fail_remember)

    with pytest.raises(OSError, match="simulated app-local persistence failure"):
        manager.select_vault(vault_b, remember=True)

    settings = AppLocalSettingsStore(app_local_path).load()
    assert settings.last_active_vault_ref == f"path:{vault_a}"
    assert set(settings.known_vaults) == {f"path:{vault_a}"}
    # The registry commit is durable, but the legacy scalar remains the
    # authoritative DORMANT selection and the manager reports the persistence
    # failure before exposing the candidate as its in-process context.
    assert runtime.registry.load().last_active_vault_ref == f"path:{vault_b}"
    assert manager.context.active_vault_path == str(vault_a)

