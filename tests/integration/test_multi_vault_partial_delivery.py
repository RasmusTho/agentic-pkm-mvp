"""Behavioral MVR-05B compatibility-mutation seals."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from tests._mvr03_principal_harness import provisioned_instance


def _setup(tmp_path, monkeypatch):
    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)
    session = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    ).json()["context_selection_id"]
    return client, session, first, extra[0]


def test_scoped_write_is_sealed_until_mvr05c(tmp_path, monkeypatch) -> None:
    client, session, _first, _second = _setup(tmp_path, monkeypatch)
    for headers in (
        {"X-Active-Context-Session": session},
        {"X-Active-Context-Override": session},
        {
            "X-Active-Context-Session": session,
            "X-Active-Context-Override": session,
        },
    ):
        capture = client.post("/api/companion/capture", headers=headers, json={"text": "must not write"})
        assert capture.status_code == 409
        assert capture.json()["detail"]["error"] == "capability_not_ready"

        save = client.post(
            "/api/companion/note/save",
            headers=headers,
            json={"note_path": "missing.md", "new_body": "must not write"},
        )
        assert save.status_code == 409
        assert save.json()["detail"]["error"] == "capability_not_ready"


def test_migrated_client_write_precondition_prevents_cross_client_compatibility_redirect(
    tmp_path, monkeypatch
) -> None:
    client, session, _first, _second = _setup(tmp_path, monkeypatch)
    response = client.post(
        "/api/companion/capture/compatibility",
        headers={"X-Active-Context-Session": session},
        json={"text": "must not write"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "capability_not_ready"


def test_migrated_write_route_rejects_stripped_precondition_without_legacy_downgrade(
    tmp_path, monkeypatch
) -> None:
    client, _session, _first, _second = _setup(tmp_path, monkeypatch)
    response = client.post(
        "/api/companion/capture/compatibility",
        json={"text": "must not write"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "capability_not_ready"
