"""Production request isolation and authority-change fencing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.instance.local_operator_principal import SUBJECT_LOOPBACK
from tests._mvr03_principal_harness import principal_store, provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0]


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


def test_two_sessions_use_distinct_vaults_without_cross_talk(instance, client, monkeypatch) -> None:
    """Two real scoped API reads hold shared fences concurrently and stay isolated."""

    runtime, first, second = instance
    first_root = runtime.registry.lookup(first.vault_binding_id)
    second_root = runtime.registry.lookup(second.vault_binding_id)
    assert first_root is not None and second_root is not None
    from pathlib import Path

    Path(first_root.path, "only-first.md").write_text("# First", encoding="utf-8")
    Path(second_root.path, "only-second.md").write_text("# Second", encoding="utf-8")
    first_session = _create(client, first.vault_binding_id)
    second_session = _create(client, second.vault_binding_id)

    entered = Barrier(2)
    from app.api.routes import companion as companion_routes

    original = companion_routes._list_vault_notes

    def paused(root, q=""):
        entered.wait(timeout=5)
        return original(root, q=q)

    # Synchronize inside the actual scoped route after it has acquired its
    # binding effect lease. This proves API-session isolation, not only a
    # helper-level filesystem projection.
    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused)

    def read(session: dict):
        response = client.get(
            "/api/companion/vault/notes/scoped",
            headers={"X-Active-Context-Session": session["context_selection_id"]},
        )
        assert response.status_code == 200, response.text
        return [
            (note["vault_binding_id"], note["path"])
            for note in response.json()["notes"]
            if note["path"].startswith("only-")
        ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(read, first_session),
            pool.submit(read, second_session),
        ]
        responses = [future.result(timeout=5) for future in futures]

    assert responses == [
        [(first.vault_binding_id, "only-first.md")],
        [(second.vault_binding_id, "only-second.md")],
    ]
    assert runtime.registry.load().default_vault_binding_id == first.vault_binding_id


def test_authority_change_cannot_cross_read_effect_window(instance, client, monkeypatch) -> None:
    """Rotation waits for a real scoped read, then invalidates its stale session."""

    runtime, first, _second = instance
    session = _create(client, first.vault_binding_id)
    entered = Event()
    release = Event()
    from app.api.routes import companion as companion_routes

    original = companion_routes._list_vault_notes

    def paused(root, q=""):
        entered.set()
        assert release.wait(timeout=5)
        return original(root, q=q)

    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused)

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = pool.submit(
            client.get,
            "/api/companion/vault/notes/scoped",
            headers={"X-Active-Context-Session": session["context_selection_id"]},
        )
        assert entered.wait(timeout=5)
        rotation_future = pool.submit(
            principal_store(runtime).rotate_credential,
            credential="rotated-for-test",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        with pytest.raises(TimeoutError):
            rotation_future.result(timeout=0.1)
        # Releasing the read lets the exclusive authority mutation acquire the
        # principal lock. Both futures must complete: no lock-order deadlock.
        release.set()
        read_response = read_future.result(timeout=5)
        rotated = rotation_future.result(timeout=5)

    assert read_response.status_code == 200, read_response.text
    assert rotated.revision == session["context"]["generation"] + 1
    stale = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert stale.status_code == 401, stale.text
    assert stale.json()["detail"] == "reselection_required: selection is not resolvable for this caller"


def test_subject_revocation_rejects_a_previously_issued_session(instance, client) -> None:
    runtime, first, _second = instance
    session = _create(client, first.vault_binding_id)
    store = principal_store(runtime)
    store.rotate_credential(
        credential="credential-to-keep-loopback-revocable",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    revoked = store.revoke_subject(
        SUBJECT_LOOPBACK,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert SUBJECT_LOOPBACK not in revoked.subjects

    stale = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert stale.status_code == 401, stale.text
    assert stale.json()["detail"] == "reselection_required"
