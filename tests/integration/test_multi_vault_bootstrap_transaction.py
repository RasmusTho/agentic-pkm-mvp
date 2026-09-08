"""MVR-05B fresh first-vault bootstrap and restart recovery."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.api.routes.active_context_selection as selection_routes
from app.api.app import app
from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.first_vault_bootstrap import FirstVaultBootstrapError, FirstVaultPreconditionStore
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests._mvr05b_bootstrap_harness import fresh_no_vault_instance


@pytest.fixture()
def fresh_bootstrap_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, principal = fresh_no_vault_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    app_local = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    selection_routes.reset_selection_store_for_tests()
    return runtime, principal, manager, tmp_path


def _bootstrap(client: TestClient, target: Path) -> dict[str, object]:
    response = client.post(
        "/api/companion/vault/initialize/bootstrap",
        json={"path": str(target), "confirm": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_http_bootstrap_binds_expiry_confirmation_and_authority(
    fresh_bootstrap_instance,
) -> None:
    runtime, principal, _manager, tmp_path = fresh_bootstrap_instance
    client = TestClient(app, raise_server_exceptions=False)
    target = tmp_path / "fresh"

    # Missing confirmation is rejected before a token exists or a target is touched.
    missing_confirmation = client.post(
        "/api/companion/vault/initialize/bootstrap",
        json={"path": str(target)},
    )
    assert missing_confirmation.status_code == 409
    assert not target.exists()

    issued = _bootstrap(client, target)
    token = str(issued["bootstrap_token"])
    assert issued["registry_revision"] == runtime.registry.load().revision
    assert issued["compatibility_revision"] == runtime.registry.load().revision
    assert token

    # The bearer is bound to the canonical target, not just to the caller's intent.
    wrong_target = client.post(
        "/api/companion/vault/initialize",
        json={
            "path": str(tmp_path / "other"),
            "confirm": True,
            "bootstrap_token": token,
        },
    )
    assert wrong_target.status_code == 409
    assert not (tmp_path / "other").exists()
    assert not runtime.registry.load().registrations

    store = FirstVaultPreconditionStore(runtime.registry.path)
    record = store.load()
    assert record is not None
    with pytest.raises(FirstVaultBootstrapError, match="principal mismatch"):
        store.require(
            token,
            principal_id=principal.local_operator_role_id + "-wrong",
            path=target,
            vault_name=None,
            machine_role="primary",
            remember=True,
            confirm=True,
            snapshot=runtime.registry.load(),
        )
    assert record.expires_at > record.issued_at
    expired_store = FirstVaultPreconditionStore(
        runtime.registry.path,
        clock=lambda: record.expires_at + 1,
    )
    with pytest.raises(FirstVaultBootstrapError, match="expired"):
        expired_store.require(
            token,
            principal_id=principal.local_operator_role_id,
            path=target,
            vault_name=None,
            machine_role="primary",
            remember=True,
            confirm=True,
            snapshot=runtime.registry.load(),
        )

    initialized = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert initialized.status_code == 200, initialized.text
    assert initialized.json()["context_selection_id"]

    replay = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["context_selection_id"]
    assert len(runtime.registry.load().registrations) == 1


def test_bootstrap_issuance_refuses_pending_same_channel_ownership(
    fresh_bootstrap_instance,
) -> None:
    """An expired-looking in-flight transition cannot be replaced by a new token."""

    runtime, _principal, _manager, tmp_path = fresh_bootstrap_instance
    client = TestClient(app, raise_server_exceptions=False)
    runtime.ledger.reserve(
        channel_id=runtime.layout.channel_id,
        vault_binding_id="binding-in-flight",
        root=tmp_path / "pending-target",
        allow_same_channel_nested=False,
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )

    response = client.post(
        "/api/companion/vault/initialize/bootstrap",
        json={"path": str(tmp_path / "replacement"), "confirm": True},
    )
    assert response.status_code == 409, response.text
    assert "ownership transition" in response.text


def test_post_effect_restart_recovers_first_initialize_forward(
    fresh_bootstrap_instance,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _principal, manager, tmp_path = fresh_bootstrap_instance
    client = TestClient(app, raise_server_exceptions=False)
    target = tmp_path / "restartable"
    issued = _bootstrap(client, target)
    token = str(issued["bootstrap_token"])

    original_initialize = manager.initialize_vault

    def fail_after_effect(*args, **kwargs):
        original_initialize(*args, **kwargs)
        raise RuntimeError("injected post-effect process loss")

    monkeypatch.setattr(manager, "initialize_vault", fail_after_effect)
    failed = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert failed.status_code == 500
    assert target.joinpath("settings", "vault.md").is_file()
    content_digest = hashlib.sha256(
        target.joinpath("settings", "vault.md").read_bytes()
    ).hexdigest()
    assert not runtime.registry.load().registrations
    assert FirstVaultPreconditionStore(runtime.registry.path).load().state == "content_effected"

    # A fresh manager/store represents a process restart. Recovery must use the existing
    # owner-native content and must not call the destructive initializer again.
    restarted_manager = VaultManager(
        app_local_store=AppLocalSettingsStore(tmp_path / "restarted-app-local.md")
    )
    def must_not_reinitialize(*args, **kwargs):
        raise AssertionError("recovery repeated the content initializer")

    monkeypatch.setattr(restarted_manager, "initialize_vault", must_not_reinitialize)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: restarted_manager)
    selection_routes.reset_selection_store_for_tests()
    recovered = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["context"]["status"] == "selected"
    assert recovered.json()["context_selection_id"]
    assert hashlib.sha256(target.joinpath("settings", "vault.md").read_bytes()).hexdigest() == content_digest
    snapshot = runtime.registry.load()
    assert snapshot.default_vault_binding_id in snapshot.registrations
    assert FirstVaultPreconditionStore(runtime.registry.path).load().state == "consumed"

    selection = client.get(
        "/api/companion/active-context/selection",
        headers={"X-Active-Context-Session": recovered.json()["context_selection_id"]},
    )
    assert selection.status_code == 200, selection.text
    assert selection.json()["context"]["vault_binding_ids"] == [snapshot.default_vault_binding_id]


def test_response_handoff_retry_reuses_consumed_bootstrap_selection(
    fresh_bootstrap_instance,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response-handoff loss can recover without repeating content effects."""

    runtime, _principal, _manager, tmp_path = fresh_bootstrap_instance
    client = TestClient(app, raise_server_exceptions=False)
    target = tmp_path / "handoff-retry"
    token = str(_bootstrap(client, target)["bootstrap_token"])
    original = companion_module._create_initialized_scoped_selection
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected response-handoff loss")
        return original(*args, **kwargs)

    monkeypatch.setattr(companion_module, "_create_initialized_scoped_selection", fail_once)
    failed = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert failed.status_code == 500
    assert len(runtime.registry.load().registrations) == 1
    assert FirstVaultPreconditionStore(runtime.registry.path).load().state == "consumed"

    recovered = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert recovered.status_code == 200, recovered.text
    selection_id = recovered.json()["context_selection_id"]
    assert selection_id

    replay = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(target), "confirm": True, "bootstrap_token": token},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["context_selection_id"]
