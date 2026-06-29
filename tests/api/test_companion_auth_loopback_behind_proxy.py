"""Loopback-trust auth behind an opt-in trusted proxy (#2654)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.auth import require_loopback_or_api_key


BRIDGE_PROXY_HOST = "172.18.0.5"


@pytest.fixture(autouse=True)
def reset_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", "")


@pytest.fixture()
def guarded_app(tmp_path: Path) -> FastAPI:
    api = FastAPI()
    browse_root = tmp_path / "vaults"
    browse_root.mkdir()
    vault = browse_root / "Niflheim"
    vault.mkdir()

    @api.get(
        "/api/companion/vault/browse",
        dependencies=[Depends(require_loopback_or_api_key)],
    )
    def browse() -> dict[str, object]:
        return {
            "path": str(browse_root),
            "entries": [{"name": vault.name, "path": str(vault), "is_vault": True}],
        }

    @api.post(
        "/api/companion/vault/select",
        dependencies=[Depends(require_loopback_or_api_key)],
    )
    def select() -> dict[str, str]:
        return {"status": "selected"}

    @api.post(
        "/api/companion/vault/initialize",
        dependencies=[Depends(require_loopback_or_api_key)],
    )
    def initialize() -> dict[str, dict[str, str]]:
        return {
            "context": {
                "status": "selected",
                "active_vault_path": str(tmp_path / "new-vault"),
            }
        }

    return api


def _client_from(app: FastAPI, host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


def _trust_bridge_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_module.settings,
        "companion_trusted_proxy_hosts",
        BRIDGE_PROXY_HOST,
    )


def test_browse_allowed_via_trusted_proxy(
    guarded_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trust_bridge_proxy(monkeypatch)

    resp = _client_from(guarded_app, BRIDGE_PROXY_HOST).get(
        "/api/companion/vault/browse",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {entry["name"] for entry in body["entries"]} == {"Niflheim"}


def test_select_and_initialize_allowed_via_trusted_proxy(
    guarded_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trust_bridge_proxy(monkeypatch)
    client = _client_from(guarded_app, BRIDGE_PROXY_HOST)
    headers = {"X-Forwarded-For": "127.0.0.1"}

    select = client.post(
        "/api/companion/vault/select",
        json={"path": "/vaults/Niflheim", "remember": True},
        headers=headers,
    )

    assert select.status_code == 200, select.text
    assert select.json()["status"] == "selected"

    initialize = client.post(
        "/api/companion/vault/initialize",
        json={"path": "/vaults/New", "vault_name": "New Vault", "remember": True},
        headers=headers,
    )

    assert initialize.status_code == 200, initialize.text
    body = initialize.json()
    assert body["context"]["status"] == "selected"


def test_untrusted_nonloopback_still_rejected(
    guarded_app: FastAPI,
) -> None:
    direct = _client_from(guarded_app, "203.0.113.10").post(
        "/api/companion/vault/select",
        json={"path": "/vaults/Niflheim", "remember": True},
    )
    untrusted_proxy = _client_from(guarded_app, BRIDGE_PROXY_HOST).post(
        "/api/companion/vault/select",
        json={"path": "/vaults/Niflheim", "remember": True},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert direct.status_code == 401
    assert untrusted_proxy.status_code == 401


def test_companion_vault_routes_use_loopback_or_api_key_guard() -> None:
    from fastapi.routing import APIRoute

    import app.api.routes.companion as companion_module

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
