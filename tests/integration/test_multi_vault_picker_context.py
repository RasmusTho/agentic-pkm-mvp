"""MVR-05B picker/watch compatibility recovery checks."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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


def test_existing_picker_drives_scoped_request_context() -> None:
    store = ContextSelectionStore()
    token, record = store.create(
        principal=PrincipalContext("owner", "human", "trusted_loopback"),
        instance_identity="instance", workspace=WorkspaceState.none(), scope="core",
        sphere_memberships=(), situated_identity=None, binding_ids=["binding-a"],
    )
    assert token and record.context_id.startswith("ctx_")


def test_legacy_picker_bridge_preserves_single_watcher_until_mvr06(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_a, vault_b = tmp_path / "a", tmp_path / "b"
    initialize_test_vault(vault_a); initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path)); monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.setattr("app.settings.ingestion.ingest_settings", lambda **_k: __import__("app.settings.ingestion", fromlist=["SettingsIngestionState"]).SettingsIngestionState(state="ok", source="vault"))
    VaultManager().select_vault(vault_b)
    assert SettingsRebindStore(registry).read().candidate_binding_id == "binding-b"


def test_interim_default_mutation_rebinds_before_foreground_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_legacy_picker_bridge_preserves_single_watcher_until_mvr06(tmp_path, monkeypatch)


def test_picker_commit_succeeds_with_durable_no_lifecycle_watcher_posture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_legacy_picker_bridge_preserves_single_watcher_until_mvr06(tmp_path, monkeypatch)


def test_prepare_drains_old_binding_writes_before_quiescent_ack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_picker_and_watcher_rebind_is_failure_atomic(tmp_path, monkeypatch)


def test_direct_filesystem_write_between_scan_and_commit_is_receipted_under_old_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_picker_and_watcher_rebind_is_failure_atomic(tmp_path, monkeypatch)


def test_picker_rebind_drains_scalar_worker_before_binding_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_legacy_picker_bridge_preserves_single_watcher_until_mvr06(tmp_path, monkeypatch)


def test_unregistered_picker_path_stops_before_manager_or_filesystem_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An arbitrary client path is only a lexical key, never a filesystem input."""
    vault_a, vault_b = tmp_path / "a", tmp_path / "b"
    initialize_test_vault(vault_a); initialize_test_vault(vault_b)
    registry = _registry(tmp_path, vault_a, vault_b)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    from app.api.routes import companion

    class _Manager:
        def select_vault(self, *_args, **_kwargs):
            raise AssertionError("unregistered request path reached vault manager")

    monkeypatch.setattr(companion, "get_vault_manager", lambda: _Manager())
    symlink_alias = tmp_path / "symlink-a"
    try:
        symlink_alias.symlink_to(vault_a, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink aliases are unavailable on this platform: {exc}")
    aliases = (
        str(tmp_path / "../unregistered"),
        str(vault_a.parent / "a/../a"),
        f"{vault_a.parent}/a//",
        f"{vault_a.parent}/./a",
        "~/a",
        str(vault_a).upper(),
        str(symlink_alias),
    )
    for alias in aliases:
        with pytest.raises(HTTPException, match="active_context_binding_unresolved"):
            companion.select_companion_vault(
                companion.VaultSelectRequest(path=alias),
                SimpleNamespace(headers={}),
            )


def test_picker_without_registry_rejects_outside_base_before_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import companion

    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
    monkeypatch.setenv("VAULT_BROWSE_ROOT", str(tmp_path / "allowed"))
    monkeypatch.setattr(companion, "get_vault_manager", lambda: pytest.fail("raw path reached manager"))
    with pytest.raises(HTTPException):
        companion.select_companion_vault(
            companion.VaultSelectRequest(path="/untrusted"), SimpleNamespace(headers={})
        )
