"""Companion loopback/proxy auth regression tests (#2706)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.auth as auth_module
from app.auth import require_loopback_or_api_key
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


UNSAFE_BRIDGE_PEER = "172.18.0.5"


@pytest.fixture(autouse=True)
def reset_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", "")


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    store_path = tmp_path / "app-local.md"
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(store_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    return mgr


def _client_from(host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


def _browse_request(
    client: TestClient,
    manager: VaultManager,
    tmp_path: Path,
    headers: dict[str, str] | None = None,
) -> tuple[object, Path | None]:
    browse_root = tmp_path / "vaults"
    browse_root.mkdir()
    manager.initialize_vault(browse_root / "Niflheim", vault_name="Niflheim", remember=False)
    response = client.get(
        "/api/companion/vault/browse",
        params={"path": str(browse_root)},
        headers=headers or {},
    )
    return response, None


def _select_request(
    client: TestClient,
    manager: VaultManager,
    tmp_path: Path,
    headers: dict[str, str] | None = None,
) -> tuple[object, Path | None]:
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)
    response = client.post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers=headers or {},
    )
    return response, None


def _initialize_request(
    client: TestClient,
    manager: VaultManager,
    tmp_path: Path,
    headers: dict[str, str] | None = None,
) -> tuple[object, Path | None]:
    vault = tmp_path / "new-vault"
    response = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(vault), "vault_name": "LAN Vault", "remember": True},
        headers=headers or {},
    )
    return response, vault


ROUTE_REQUESTS = (
    _browse_request,
    _select_request,
    _initialize_request,
)


@pytest.mark.parametrize("route_request", ROUTE_REQUESTS, ids=("browse", "select", "initialize"))
def test_non_loopback_vault_routes_require_auth(
    manager: VaultManager,
    tmp_path: Path,
    route_request,
) -> None:
    response, created_path = route_request(_client_from("203.0.113.10"), manager, tmp_path)

    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"
    if created_path is not None:
        assert not created_path.exists()


def test_loopback_proxy_forwarded_non_loopback_requires_auth(
    manager: VaultManager,
    tmp_path: Path,
) -> None:
    response, _ = _select_request(
        _client_from("127.0.0.1"),
        manager,
        tmp_path,
        headers={"X-Forwarded-For": "203.0.113.10"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"


@pytest.mark.parametrize("route_request", ROUTE_REQUESTS, ids=("browse", "select", "initialize"))
def test_spoofed_forwarded_loopback_from_unsafe_bridge_peer_is_rejected(
    manager: VaultManager,
    tmp_path: Path,
    route_request,
) -> None:
    response, created_path = route_request(
        _client_from(UNSAFE_BRIDGE_PEER),
        manager,
        tmp_path,
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"
    if created_path is not None:
        assert not created_path.exists()


@pytest.mark.parametrize("route_request", ROUTE_REQUESTS, ids=("browse", "select", "initialize"))
def test_forwarded_loopback_from_configured_bridge_proxy_is_allowed(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_request,
) -> None:
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", UNSAFE_BRIDGE_PEER)

    response, created_path = route_request(
        _client_from(UNSAFE_BRIDGE_PEER),
        manager,
        tmp_path,
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 200
    if created_path is not None:
        assert created_path.exists()


def test_loopback_local_select_is_allowed_without_api_key(
    manager: VaultManager,
    tmp_path: Path,
) -> None:
    response, _ = _select_request(_client_from("127.0.0.1"), manager, tmp_path)

    assert response.status_code == 200
    assert response.json()["status"] == "selected"


@pytest.mark.parametrize("route_request", ROUTE_REQUESTS, ids=("browse", "select", "initialize"))
def test_loopback_proxy_forwarded_non_loopback_with_api_key_is_allowed(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_request,
) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", "uat-secret")

    response, created_path = route_request(
        _client_from("127.0.0.1"),
        manager,
        tmp_path,
        headers={"X-Forwarded-For": "203.0.113.10", "X-API-Key": "uat-secret"},
    )

    assert response.status_code == 200
    if created_path is not None:
        assert created_path.exists()


def test_direct_non_loopback_with_api_key_is_allowed(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", "uat-secret")

    response, _ = _select_request(
        _client_from("203.0.113.10"),
        manager,
        tmp_path,
        headers={"X-API-Key": "uat-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "selected"


def test_companion_vault_routes_use_loopback_or_api_key_guard() -> None:
    from fastapi.routing import APIRoute

    guarded_paths = {
        "/companion/vault/browse",
        "/companion/vault/select",
        "/companion/vault/initialize",
    }
    route_dependencies = {
        route.path: {dependency.call for dependency in route.dependant.dependencies}
        for route in companion_module.router.routes
        if isinstance(route, APIRoute) and route.path in guarded_paths
    }

    assert set(route_dependencies) == guarded_paths
    for dependencies in route_dependencies.values():
        assert require_loopback_or_api_key in dependencies
