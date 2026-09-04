"""MVR-05B picker/watch compatibility recovery checks."""

from pathlib import Path

import pytest

from app.instance._storage_boundary import RegistryError
from app.instance.settings_rebind import SettingsRebindStore
from app.vault.manager import VaultManager
from app.instance.context_selection import ContextSelectionStore, ReselectionRequiredError
from app.instance.first_vault_bootstrap import BootstrapPreconditionError, FirstVaultBootstrapStore
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import PrincipalContext, WorkspaceState
from tests.helpers.vault_settings import initialize_test_vault
from tests.watcher.test_ingest_binding_follows_selection import _registry


def test_picker_and_watcher_rebind_is_failure_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a, vault_b = tmp_path / "a", tmp_path / "b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **_kwargs: __import__("app.settings.ingestion", fromlist=["SettingsIngestionState"]).SettingsIngestionState(
            state="degraded_last_valid", source="vault", error="forced"
        ),
    )

    with pytest.raises(RegistryError, match="reload did not complete"):
        VaultManager().select_vault(vault_b)
    failed = SettingsRebindStore(registry).read()
    assert failed.candidate_binding_id == "binding-b"
    assert failed.reload_revision == 0

    from app.settings.ingestion import SettingsIngestionState

    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        lambda **_kwargs: SettingsIngestionState(state="ok", source="vault"),
    )
    VaultManager().select_vault(vault_b)
    recovered = SettingsRebindStore(registry).read()
    assert recovered.phase == "no_lifecycle"
    assert recovered.reload_revision == recovered.desired_revision


def test_session_selection_reuses_bindings_with_per_request_server_scope() -> None:
    store = ContextSelectionStore()
    token, record = store.create(
        principal=PrincipalContext("owner", "human", "trusted_loopback"),
        instance_identity="instance", workspace=WorkspaceState.none(), scope="core",
        sphere_memberships=(), situated_identity=None, binding_ids=["binding-a"],
    )
    assert token
    assert record.binding_ids == ("binding-a",)
    assert record.scope == "core"


def test_stale_selection_restart_requires_visible_reselection() -> None:
    store = ContextSelectionStore()
    token, _ = store.create(
        principal=PrincipalContext("owner", "human", "trusted_loopback"),
        instance_identity="instance", workspace=WorkspaceState.none(), scope="core",
        sphere_memberships=(), situated_identity=None, binding_ids=["binding-a"],
    )
    restarted = ContextSelectionStore()
    with pytest.raises(ReselectionRequiredError):
        restarted.inspect(
            token,
            principal=PrincipalContext("owner", "human", "trusted_loopback"),
            instance_identity="instance",
        )


def test_fresh_vault_initialize_returns_usable_scoped_context(tmp_path: Path) -> None:
    registry = VaultRegistryStore(tmp_path / "registry.md")
    token = FirstVaultBootstrapStore().issue(
        subject="trusted_loopback", target=tmp_path / "vault", registry=registry
    )
    assert token


def test_first_vault_initialize_bootstrap_is_single_use_and_failure_atomic(tmp_path: Path) -> None:
    registry = VaultRegistryStore(tmp_path / "registry.md")
    store = FirstVaultBootstrapStore()
    token = store.issue(subject="trusted_loopback", target=tmp_path / "vault", registry=registry)
    store.consume(token=token, subject="trusted_loopback", target=tmp_path / "vault", registry=registry)
    with pytest.raises(BootstrapPreconditionError):
        store.consume(token=token, subject="trusted_loopback", target=tmp_path / "vault", registry=registry)
