from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_vault_context_response_includes_active_context_projection(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    selected = tmp_path / "selected-vault"
    manager.initialize_vault(selected, vault_name="Selected Vault", machine_role="testNode")
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)

    resp = client.get("/api/companion/vault/context")

    assert resp.status_code == 200
    active_context = resp.json()["active_context"]
    assert active_context["version"] == "active_context_set.v0"
    assert active_context["context_id"]["status"] == "unknown"
    assert active_context["context_id"]["value"] is None
    assert active_context["workspace"]["status"] == "unknown"
    assert active_context["scope"]["status"] == "unknown"
    assert active_context["sphere"]["status"] == "unknown"
    assert active_context["situated_identity"]["status"] == "unknown"
    assert active_context["situated_identity"]["value"] is None
    assert active_context["principal_context"]["status"] == "unknown"
    assert active_context["principal_context"]["value"] is None
    assert active_context["topology_posture"]["value"] == "single-node"
    assert active_context["source_bindings"][0]["binding_ref"] == str(selected)
    assert active_context["source_bindings"][0]["implementation_detail"] is True
