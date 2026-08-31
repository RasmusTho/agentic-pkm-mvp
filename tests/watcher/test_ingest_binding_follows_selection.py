"""SETTINGS-05C foreground activation and durable health truth."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.instance._storage_boundary import RegistryError
from app.settings.ingestion import SettingsIngestionState
from app.api.routes.ingest_binding import ingest_binding_status
from app.instance.settings_rebind import (
    SettingsRebindStore,
    _install_dormant_settings_rebind,
)
from app.instance.vault_registry import KnownVaultRef, VaultRegistration, VaultRegistryStore
from app.vault.manager import VaultManager
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _successful_reload(**kwargs: object) -> SettingsIngestionState:
    del kwargs
    return SettingsIngestionState(state="ok", source="vault")


def _registry(tmp_path: Path, vault_a: Path, vault_b: Path) -> VaultRegistryStore:
    registry = VaultRegistryStore(tmp_path / "instance-state" / "vault-registry.md")
    registry.register(
        VaultRegistration("binding-a", "path:" + str(vault_a), str(vault_a)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    registry.register(
        VaultRegistration("binding-b", "path:" + str(vault_b), str(vault_b)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    _install_dormant_settings_rebind(
        registry,
        binding_id="binding-a",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return registry


def _selection(registration: VaultRegistration) -> KnownVaultRef:
    return KnownVaultRef(
        ref=registration.ref,
        path=registration.path,
        vault_id=registration.vault_id,
        vault_name=registration.vault_name,
        local_instance_id=registration.local_instance_id,
        last_opened_at="2026-08-30T00:00:00Z",
    )


def _heartbeat(path: Path, vault: Path) -> None:
    path.write_text(
        json.dumps({"ts": time.time(), "vault_path": str(vault)}),
        encoding="utf-8",
    )


def test_selection_rebinds_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("WATCHER_ENABLE", "0")

    reloads: list[Path] = []
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **kwargs: (reloads.append(Path(kwargs["vault_root"])), _successful_reload())[1],
    )
    manager = VaultManager()
    context = manager.select_vault(vault_b)

    record = SettingsRebindStore(registry).read()
    assert context.active_vault_path == str(vault_b)
    assert record.phase == "no_lifecycle"
    assert record.desired_revision == record.applied_revision == 1
    assert registry.load().last_active_vault_ref == "path:" + str(vault_b)
    assert reloads == [vault_b]


def test_switch_is_clean_and_truthful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    heartbeat = tmp_path / "heartbeat.json"
    _heartbeat(heartbeat, vault_a)

    prepared = SettingsRebindStore(registry).prepare(candidate_binding_id="binding-b")
    status = ingest_binding_status(
        selected_vault_path=str(vault_b), heartbeat_path=heartbeat
    )

    assert prepared.phase == "prepared"
    assert prepared.desired_revision == 1
    assert prepared.applied_revision == 0
    assert status.rebind_phase == "prepared"
    assert status.rebind_desired_revision == 1
    assert status.rebind_applied_revision == 0
    assert status.rebind_failure_posture == "awaiting_watcher"
    assert status.watcher_vault_path == str(vault_a)


def test_rebind_reloads_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    calls: list[str] = []
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **kwargs: (calls.append(kwargs["reason"]), _successful_reload())[1],
    )

    from app.instance.settings_rebind import SettingsRebindActivation

    activation = SettingsRebindActivation.from_environment(registry)
    registration = registry.load().registrations["binding-b"]
    activation.activate(
        selection=_selection(registration),
        candidate_binding_id="binding-b",
        candidate_root=vault_b,
    )

    assert calls == ["vault_selection_rebind"]
    assert SettingsRebindStore(registry).read().applied_revision == 1


def test_completed_no_lifecycle_revision_allows_next_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed foreground rebind can start the next monotonic revision."""
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    reloads: list[Path] = []
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **kwargs: (reloads.append(Path(kwargs["vault_root"])), _successful_reload())[1],
    )

    manager = VaultManager()
    manager.select_vault(vault_b)
    manager.select_vault(vault_a)

    record = SettingsRebindStore(registry).read()
    assert record.phase == "no_lifecycle"
    assert record.desired_revision == record.applied_revision == 2
    assert record.candidate_binding_id == "binding-a"
    assert reloads == [vault_b, vault_a]


def test_failed_settings_reload_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded SETTINGS-01 result cannot advance the durable reload marker."""
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **_kwargs: SettingsIngestionState(
            state="degraded_last_valid", source="vault", error="invalid source"
        ),
    )

    with pytest.raises(RegistryError, match="SETTINGS-01 reload did not complete successfully"):
        VaultManager().select_vault(vault_b)

    record = SettingsRebindStore(registry).read()
    assert record.phase == "no_lifecycle"
    assert record.reload_revision == 0


def test_novault_transitions_truthful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    heartbeat = tmp_path / "heartbeat.json"
    _heartbeat(heartbeat, vault_a)

    status = ingest_binding_status(selected_vault_path=None, heartbeat_path=heartbeat)

    assert status.state == "unknown"
    assert status.rebind_schema == "settings_rebind.v1"
    assert status.rebind_phase == "dormant"
    assert status.rebind_desired_revision == 0
    assert status.rebind_applied_revision == 0
