"""Auth posture for state-changing companion vault routes (#2223)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.auth as auth_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture(autouse=True)
def reset_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    store_path = tmp_path / "app-local.md"
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(store_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    return mgr


def _client_from(host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


def test_vault_select_requires_auth_when_non_loopback(
    manager: VaultManager,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)

    resp = _client_from("203.0.113.10").post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
    )

    assert resp.status_code == 401


def test_vault_initialize_requires_auth_when_non_loopback(tmp_path: Path) -> None:
    vault = tmp_path / "new-vault"

    resp = _client_from("203.0.113.10").post(
        "/api/companion/vault/initialize",
        json={"path": str(vault), "vault_name": "LAN Vault", "remember": True},
    )

    assert resp.status_code == 401
    assert not vault.exists()


def test_vault_select_requires_auth_when_loopback_proxy_forwards_non_loopback(
    manager: VaultManager,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)

    resp = _client_from("127.0.0.1").post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )

    assert resp.status_code == 401


def test_vault_select_allowed_on_loopback_or_with_key(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)

    loopback = _client_from("127.0.0.1").post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
    )
    assert loopback.status_code == 200
    assert loopback.json()["status"] == "selected"

    monkeypatch.setattr(auth_module.settings, "api_key", "uat-secret")
    lan = _client_from("203.0.113.10").post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-API-Key": "uat-secret"},
    )
    assert lan.status_code == 200
    assert lan.json()["status"] == "selected"

    proxied_lan = _client_from("127.0.0.1").post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-Forwarded-For": "203.0.113.10", "X-API-Key": "uat-secret"},
    )
    assert proxied_lan.status_code == 200
    assert proxied_lan.json()["status"] == "selected"
