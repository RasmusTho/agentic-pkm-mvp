"""Behavioural guards for the migrated backend read ingress."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import ask as ask_routes
from app.instance._storage_boundary import CapabilityNotReadyError
from tests._mvr03_principal_harness import provisioned_instance

SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_global_vault_manager(monkeypatch):
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    yield


def _create(client: TestClient, binding_id: str) -> dict:
    response = client.post(SELECTION_URL, json={"vault_binding_ids": [binding_id]})
    assert response.status_code == 201, response.text
    return response.json()


def test_migrated_scoped_read_rejects_stripped_carrier_without_default_downgrade(
    instance, client, monkeypatch
) -> None:
    """A scoped route fails before ASK and cannot fall back to the legacy default."""

    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_kw: pytest.fail("ASK ran"))
    response = client.post("/api/ask/scoped", json={"question": "which context?"})

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "reselection_required"


def test_invalid_override_fails_closed_without_falling_back_to_session(
    instance, client, monkeypatch
) -> None:
    _runtime, first = instance
    session = _create(client, first.vault_binding_id)
    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_kw: pytest.fail("ASK ran"))

    response = client.post(
        "/api/ask/scoped",
        json={"question": "which context?"},
        headers={
            "X-Active-Context-Session": session["context_selection_id"],
            "X-Active-Context-Override": "stale-override",
        },
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("reselection_required")
    assert "stale-override" not in response.text


def test_backend_read_enabling_preserves_dormant_producers(instance, client, monkeypatch) -> None:
    """All scoped read producers work while legacy/picker writes remain dormant."""

    runtime, first = instance
    session = _create(client, first.vault_binding_id)
    scoped = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["context_generation"] == 1

    search = client.get(
        "/search/scoped?q=backend",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert search.status_code == 200, search.text
    assert "results" in search.json()

    import app.agents.ask.graph as ask_graph

    monkeypatch.setattr(
        ask_graph,
        "get_vault_manager",
        lambda: pytest.fail("scoped ASK must not consult the global vault manager"),
    )
    ask = client.post(
        "/api/ask/scoped",
        json={"question": "backend"},
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert ask.status_code == 200, ask.text
    assert "answer" in ask.json()

    # The shipped legacy route still uses its existing global-selection adapter;
    # enabling the backend carrier never silently activates the picker or rewires
    # that producer into the scoped route.
    legacy = client.get("/api/companion/vault/notes")
    assert legacy.status_code == 200, legacy.text
    assert "context_generation" not in legacy.json()

    # The actual dormant producer methods remain fail-closed after scoped reads;
    # route inventory alone would not prove that the capability gate still holds.
    with pytest.raises(CapabilityNotReadyError, match="MVR-06B"):
        runtime.remove(first.vault_binding_id)
    with pytest.raises(CapabilityNotReadyError, match="MVR-06C"):
        runtime.relocate(first.vault_binding_id, runtime.layout.root / "relocated")
    with pytest.raises(CapabilityNotReadyError, match="MVR-05C"):
        runtime.transfer_to(runtime, first.vault_binding_id)

    # No scoped read implicitly activates the not-ready picker/write routes.
    assert not any(
        route.path.endswith("/remove") or route.path.endswith("/relocate") or route.path.endswith("/transfer")
        for route in client.app.routes
        if hasattr(route, "path")
    )
