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

    # MVR-05B2: the migrated companion read routes (the same URLs the legacy
    # carrier-free journey uses) bind to each request's own context while both
    # requests hold their shared binding leases concurrently.
    migrated_entered = Barrier(2)

    def paused_migrated(root, q=""):
        migrated_entered.wait(timeout=5)
        return original(root, q=q)

    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused_migrated)

    def read_migrated(session: dict):
        headers = {"X-Active-Context-Session": session["context_selection_id"]}
        response = client.get("/api/companion/vault/notes", headers=headers)
        assert response.status_code == 200, response.text
        context = client.get("/api/companion/vault/context", headers=headers)
        assert context.status_code == 200, context.text
        return (
            sorted(
                note["path"] for note in response.json()["notes"] if note["path"].startswith("only-")
            ),
            context.json()["active_vault_path"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(read_migrated, first_session),
            pool.submit(read_migrated, second_session),
        ]
        migrated = [future.result(timeout=5) for future in futures]

    assert migrated == [
        (["only-first.md"], str(Path(first_root.path).resolve())),
        (["only-second.md"], str(Path(second_root.path).resolve())),
    ]
    # Neither scoped read consulted or created the process-wide selector.
    import app.vault.manager as vault_manager_module

    assert vault_manager_module._GLOBAL_MANAGER is None
    assert runtime.registry.load().default_vault_binding_id == first.vault_binding_id


def test_authority_change_cannot_cross_read_effect_window(instance, client, monkeypatch) -> None:
    """Rotation waits for real scoped reads, then invalidates their stale session.

    Both the dedicated scoped route and a migrated companion read route (MVR-05B2)
    hold the shared binding lease from final revalidation through response
    publication, so the exclusive authority mutation cannot cross either.
    """

    runtime, first, _second = instance
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}
    read_routes = ("/api/companion/vault/notes/scoped", "/api/companion/vault/notes")
    entered = Barrier(len(read_routes) + 1)
    release = Event()
    from app.api.routes import companion as companion_routes

    original = companion_routes._list_vault_notes

    def paused(root, q=""):
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        return original(root, q=q)

    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused)

    with ThreadPoolExecutor(max_workers=len(read_routes) + 1) as pool:
        read_futures = [pool.submit(client.get, route, headers=headers) for route in read_routes]
        entered.wait(timeout=5)
        rotation_future = pool.submit(
            principal_store(runtime).rotate_credential,
            credential="rotated-for-test",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        with pytest.raises(TimeoutError):
            rotation_future.result(timeout=0.1)
        # Releasing the reads lets the exclusive authority mutation acquire the
        # principal lock. Every future must complete: no lock-order deadlock.
        release.set()
        read_responses = [future.result(timeout=5) for future in read_futures]
        rotated = rotation_future.result(timeout=5)

    for read_response in read_responses:
        assert read_response.status_code == 200, read_response.text
    assert rotated.revision == session["context"]["generation"] + 1
    for route in read_routes:
        stale = client.get(route, headers=headers)
        assert stale.status_code == 401, stale.text
        assert (
            stale.json()["detail"]
            == "reselection_required: selection is not resolvable for this caller"
        )


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


def test_explicit_empty_selection_renders_no_vault_state_without_legacy_lookup(
    instance, client, monkeypatch
) -> None:
    """#6156 review: a healthy zero-binding selection is the scoped no-vault journey."""

    from app.api.routes import companion as companion_routes

    def legacy_forbidden(*_args, **_kwargs):
        raise AssertionError("scoped no-vault read consulted the legacy process-wide selection")

    monkeypatch.setattr(companion_routes, "_legacy_companion_vault_manager", legacy_forbidden)
    monkeypatch.setattr(companion_routes, "_legacy_configured_vault_root", legacy_forbidden)
    response = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert response.status_code == 201, response.text
    headers = {"X-Active-Context-Session": response.json()["context_selection_id"]}

    notes = client.get("/api/companion/vault/notes", headers=headers)
    context = client.get("/api/companion/vault/context", headers=headers)

    for result in (notes, context):
        assert result.status_code == 200, result.text
        assert "active_context_single_binding_required" not in result.text
    assert "no_vault_bound" in notes.text
    assert context.json().get("active_vault_path") in (None, "")


def test_explicit_empty_selection_reads_inside_the_principal_effect_window(
    instance, client, monkeypatch
) -> None:
    """#6156 review: the zero-binding journey keeps the read-to-publication fence."""

    from contextlib import contextmanager

    from app.api.routes import companion as companion_routes

    original = companion_routes.context_bound_read_window
    entered: list[int] = []

    @contextmanager
    def recording(context, **kwargs):
        with original(context, **kwargs) as roots:
            entered.append(len(roots))
            yield roots

    monkeypatch.setattr(companion_routes, "context_bound_read_window", recording)
    response = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert response.status_code == 201, response.text
    headers = {"X-Active-Context-Session": response.json()["context_selection_id"]}

    browse = client.get("/api/companion/vault/browse", headers=headers)

    assert browse.status_code == 200, browse.text
    assert entered == [0]


def test_scoped_reads_omit_process_global_artifact_projections(instance, client, monkeypatch) -> None:
    """#6156 review: receipts, memory posture and panel stores are not binding-aware yet."""

    from pathlib import Path

    from app.api.routes import companion as companion_routes

    def forbidden(*_args, **_kwargs):
        raise AssertionError("scoped read consulted a process-global artifact projection")

    monkeypatch.setattr(companion_routes, "receipts_for_artifacts", forbidden)
    monkeypatch.setattr(companion_routes, "agent_memory_posture_for_artifacts", forbidden)
    monkeypatch.setattr(companion_routes, "_proposal_count_for_artifact", forbidden)
    runtime, first, _second = instance
    first_root = runtime.registry.lookup(first.vault_binding_id)
    assert first_root is not None
    Path(first_root.path, "shared.md").write_text("# Shared\n", encoding="utf-8")
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}

    browser = client.get("/api/companion/vault-browser", headers=headers)
    workspace = client.get(
        "/api/companion/workspace", params={"note_path": "shared.md"}, headers=headers
    )

    assert browser.status_code == 200, browser.text
    assert all(note.get("receipts") in ([], None) for note in browser.json()["notes"])
    assert workspace.status_code == 200, workspace.text
    panel = workspace.json()["panel"]
    assert panel["proposal_count"] == 0
    assert panel["receipt_count"] == 0


def test_scoped_now_orientation_and_browse_stay_inside_the_bound_vault(
    instance, client, monkeypatch
) -> None:
    """#6156 review: /now nudges, orientation stores and browse base are binding-confined."""

    from pathlib import Path

    from app.api.routes import companion as companion_routes
    from app.relevance import now_surface

    def forbidden(*_args, **_kwargs):
        raise AssertionError("scoped read consulted a process-global source")

    monkeypatch.setattr(now_surface, "query_reachout_receipts", forbidden)
    monkeypatch.setattr(companion_routes, "_orientation_memory_review_queue", forbidden)
    monkeypatch.setattr(companion_routes, "_proposal_count_for_artifact", forbidden)
    monkeypatch.delenv("VAULT_BROWSE_ROOT", raising=False)
    runtime, first, _second = instance
    first_root = runtime.registry.lookup(first.vault_binding_id)
    assert first_root is not None
    from tests.helpers.vault_settings import initialize_test_vault

    initialize_test_vault(Path(first_root.path))
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}

    now = client.get("/api/companion/now", headers=headers)
    orientation = client.get("/api/companion/orientation", headers=headers)
    browse = client.get("/api/companion/vault/browse", headers=headers)

    assert now.status_code == 200, now.text
    assert orientation.status_code == 200, orientation.text
    body = orientation.json()
    assert body["memory"]["pending_candidate_count"] == 0
    assert body["governance"]["pending_proposal_count"] == 0
    assert browse.status_code == 200, browse.text
    assert browse.json()["base"] == str(Path(first_root.path).resolve())
